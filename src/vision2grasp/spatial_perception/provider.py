"""Mask-aware depth statistics and camera-frame backprojection."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time

import cv2
import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import CameraIntrinsics
from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import (
    CalibrationState,
    DepthFrame,
    DepthMode,
    DepthSource,
    GeometrySanity,
    GeometrySanityStatus,
    IntrinsicsSource,
    SpatialGeometryDiagnostics,
    SpatialObservation,
    SpatialStage,
    TargetDepth,
)
from .interfaces import CameraIntrinsicsProvider, DepthProvider, SpatialProgressCallback


@dataclass(frozen=True, slots=True)
class MaskSpatialPerceptionConfig:
    minimum_valid_depth_ratio: float = 0.50
    minimum_points: int = 30
    maximum_points: int = 4096
    outlier_mad_scale: float = 3.5
    minimum_depth_band: float = 0.02
    diagnostic_extent_lower_quantile: float = 0.02
    diagnostic_extent_upper_quantile: float = 0.98

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_valid_depth_ratio <= 1.0:
            raise ValueError("minimum_valid_depth_ratio must be in (0, 1]")
        if self.minimum_points <= 0:
            raise ValueError("minimum_points must be positive")
        if self.maximum_points < self.minimum_points:
            raise ValueError("maximum_points must be at least minimum_points")
        if self.outlier_mad_scale <= 0.0 or self.minimum_depth_band <= 0.0:
            raise ValueError("depth filtering parameters must be positive")
        if not (
            0.0
            <= self.diagnostic_extent_lower_quantile
            < self.diagnostic_extent_upper_quantile
            <= 1.0
        ):
            raise ValueError("diagnostic extent quantiles must be ordered inside [0, 1]")


class MaskSpatialPerceptionProvider:
    """Produce a model-neutral SpatialObservation from one frozen snapshot."""

    def __init__(
        self,
        depth_provider: DepthProvider,
        intrinsics_provider: CameraIntrinsicsProvider,
        config: MaskSpatialPerceptionConfig | None = None,
    ) -> None:
        self._depth_provider = depth_provider
        self._intrinsics_provider = intrinsics_provider
        self._config = config or MaskSpatialPerceptionConfig()

    @property
    def model_ready(self) -> bool:
        return bool(getattr(self._depth_provider, "model_ready", False))

    def cancel_current(self) -> None:
        cancel = getattr(self._depth_provider, "cancel_current", None)
        if callable(cancel):
            cancel()

    def close(self) -> None:
        close = getattr(self._depth_provider, "close", None)
        if callable(close):
            close()

    def analyze(
        self,
        snapshot: TargetSceneSnapshot,
        progress: SpatialProgressCallback | None = None,
    ) -> SpatialObservation:
        self._emit(progress, SpatialStage.SCENE_PREPARING)
        frame = snapshot.frame
        target = snapshot.target
        self._validate_snapshot(snapshot)
        depth_frame = self._depth_provider.infer(frame, progress)
        if depth_frame.source_frame_id != frame.frame_id:
            raise ValueError("depth source_frame_id does not match Scene Snapshot")
        if depth_frame.source_timestamp_s != frame.timestamp_s:
            raise ValueError("depth timestamp does not match Scene Snapshot")
        if depth_frame.values.shape != frame.rgb.shape[:2]:
            raise ValueError("depth frame shape does not match Scene Snapshot")

        intrinsics_observation = self._intrinsics_provider.resolve(frame)
        intrinsics = intrinsics_observation.intrinsics
        self._validate_intrinsics(intrinsics)
        if (intrinsics.width, intrinsics.height) != (
            frame.rgb.shape[1],
            frame.rgb.shape[0],
        ):
            raise ValueError("camera intrinsics do not match Scene Snapshot dimensions")

        self._emit(
            progress,
            SpatialStage.POINT_CLOUD_BUILDING,
            {
                "model_load_s": depth_frame.model_load_time_s,
                "depth_inference_s": depth_frame.inference_time_s,
                "model_was_ready": depth_frame.model_was_ready,
            },
        )
        point_cloud_started = time.perf_counter()
        mask = np.asarray(target.mask, dtype=np.bool_)
        mask_pixel_count = int(np.count_nonzero(mask))
        if mask_pixel_count == 0:
            raise ValueError("target mask is empty")
        valid = mask & np.isfinite(depth_frame.values) & (depth_frame.values > 0.0)
        valid_count = int(np.count_nonzero(valid))
        valid_ratio = valid_count / mask_pixel_count
        if valid_ratio < self._config.minimum_valid_depth_ratio:
            raise ValueError(
                "valid target depth ratio below minimum: "
                f"{valid_ratio:.6f} < {self._config.minimum_valid_depth_ratio:.6f}"
            )
        if valid_count < self._config.minimum_points:
            raise ValueError(
                f"valid target depth pixels below minimum: {valid_count} < "
                f"{self._config.minimum_points}"
            )

        rows, columns = np.nonzero(valid)
        depths = np.asarray(depth_frame.values[rows, columns], dtype=np.float64)
        inliers = self._depth_inliers(depths)
        rows = rows[inliers]
        columns = columns[inliers]
        depths = depths[inliers]
        inlier_count = int(depths.size)
        if inlier_count < self._config.minimum_points:
            raise ValueError(
                f"target depth inliers below minimum: {inlier_count} < "
                f"{self._config.minimum_points}"
            )

        x = (columns.astype(np.float64) - intrinsics.cx) * depths / intrinsics.fx
        y = (rows.astype(np.float64) - intrinsics.cy) * depths / intrinsics.fy
        all_points = np.column_stack((x, y, depths))
        if all_points.size == 0 or not np.all(np.isfinite(all_points)):
            raise ValueError("target point cloud is empty or invalid")
        centroid = np.mean(all_points, axis=0)
        selected = self._sample_indices(all_points.shape[0])
        points = np.asarray(all_points[selected], dtype=np.float32)
        point_cloud_time_s = time.perf_counter() - point_cloud_started

        result_mode = self._result_depth_mode(
            source=depth_frame.source,
            native_mode=depth_frame.native_mode,
            calibration_state=intrinsics_observation.calibration_state,
        )
        target_depth = TargetDepth(
            value=float(np.median(depths)),
            valid_ratio=float(valid_ratio),
            inlier_ratio=float(inlier_count / valid_count),
            valid_pixel_count=valid_count,
            inlier_pixel_count=inlier_count,
        )
        self._emit(
            progress,
            SpatialStage.SPATIAL_COMPUTING,
            {
                "model_load_s": depth_frame.model_load_time_s,
                "depth_inference_s": depth_frame.inference_time_s,
                "point_cloud_s": point_cloud_time_s,
                "model_was_ready": depth_frame.model_was_ready,
            },
        )
        diagnostics = self._geometry_diagnostics(
            snapshot=snapshot,
            depth_frame=depth_frame,
            intrinsics=intrinsics,
            intrinsics_source=intrinsics_observation.source,
            calibration_state=intrinsics_observation.calibration_state,
            depth_mode=result_mode,
            mask=mask,
            target_depth=target_depth,
            all_points=all_points,
            centroid=centroid,
        )
        sanity = self._geometry_sanity(
            diagnostics=diagnostics,
            centroid=centroid,
            points=points,
        )
        return SpatialObservation(
            snapshot_id=snapshot.snapshot_id,
            geometry_chain_id=snapshot.geometry_chain_id,
            source_frame_id=frame.frame_id,
            target_instance_id=target.instance_id,
            source_timestamp_s=frame.timestamp_s,
            depth_frame=depth_frame,
            target_depth=target_depth,
            centroid_xyz=centroid,
            target_point_cloud=points,
            camera_intrinsics=intrinsics_observation,
            depth_source=depth_frame.source,
            depth_mode=result_mode,
            inference_time_s=depth_frame.inference_time_s,
            geometry_sanity=sanity,
            geometry_diagnostics=diagnostics,
        )

    def _geometry_diagnostics(
        self,
        *,
        snapshot: TargetSceneSnapshot,
        depth_frame: DepthFrame,
        intrinsics: CameraIntrinsics,
        intrinsics_source: IntrinsicsSource,
        calibration_state: CalibrationState,
        depth_mode: DepthMode,
        mask: NDArray[np.bool_],
        target_depth: TargetDepth,
        all_points: NDArray[np.float64],
        centroid: NDArray[np.float64],
    ) -> SpatialGeometryDiagnostics:
        frame_height, frame_width = snapshot.frame.rgb.shape[:2]
        depth_height, depth_width = depth_frame.values.shape
        mask_height, mask_width = mask.shape
        hfov = math.degrees(2.0 * math.atan(frame_width / (2.0 * intrinsics.fx)))
        vfov = math.degrees(2.0 * math.atan(frame_height / (2.0 * intrinsics.fy)))
        x1, y1, x2, y2 = snapshot.target.bbox_xyxy
        bbox_area = max((x2 - x1) * (y2 - y1), 1.0)
        mask_pixel_count = int(np.count_nonzero(mask))
        component_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8),
            connectivity=8,
        )
        foreground_areas = stats[1:, cv2.CC_STAT_AREA]
        largest_component = int(foreground_areas.max()) if foreground_areas.size else 0
        lower = self._config.diagnostic_extent_lower_quantile
        upper = self._config.diagnostic_extent_upper_quantile
        bounds = np.quantile(all_points, [lower, upper], axis=0)
        extent = np.maximum(bounds[1] - bounds[0], 0.0)
        return SpatialGeometryDiagnostics(
            snapshot_size=(frame_width, frame_height),
            depth_size=(depth_width, depth_height),
            mask_size=(mask_width, mask_height),
            model_input_size=depth_frame.model_input_size,
            geometry_chain_id=snapshot.geometry_chain_id,
            fx=float(intrinsics.fx),
            fy=float(intrinsics.fy),
            cx=float(intrinsics.cx),
            cy=float(intrinsics.cy),
            intrinsics_source=intrinsics_source,
            calibration_state=calibration_state,
            depth_mode=depth_mode,
            nominal_hfov_deg=float(hfov),
            nominal_vfov_deg=float(vfov),
            target_bbox_pixels=tuple(float(value) for value in snapshot.target.bbox_xyxy),
            target_mask_pixel_count=mask_pixel_count,
            target_mask_bbox_fill_ratio=float(mask_pixel_count / bbox_area),
            target_mask_component_count=int(component_count - 1),
            target_mask_largest_component_ratio=float(largest_component / mask_pixel_count),
            target_depth_median=float(target_depth.value),
            valid_depth_ratio=float(target_depth.valid_ratio),
            point_cloud_extent_xyz=np.asarray(extent, dtype=np.float64),
            target_centroid_xyz=np.asarray(centroid, dtype=np.float64),
            extent_quantiles=(lower, upper),
            geometry_aligned=(
                (frame_width, frame_height)
                == (depth_width, depth_height)
                == (mask_width, mask_height)
                == (intrinsics.width, intrinsics.height)
            ),
            depth_resize_policy=depth_frame.resize_policy,
        )

    @staticmethod
    def _geometry_sanity(
        *,
        diagnostics: SpatialGeometryDiagnostics,
        centroid: NDArray[np.float64],
        points: NDArray[np.float32],
    ) -> GeometrySanity:
        if not diagnostics.geometry_aligned:
            raise ValueError("geometry sanity rejected mismatched coordinate systems")
        if not np.all(np.isfinite(points)) or points.shape[0] == 0:
            raise ValueError("geometry sanity rejected invalid point cloud")
        if not np.all(np.isfinite(centroid)) or centroid[2] <= 0.0:
            raise ValueError("geometry sanity rejected invalid target centroid")
        if diagnostics.target_depth_median <= 0.0:
            raise ValueError("geometry sanity rejected non-positive target depth")
        return GeometrySanity(
            status=GeometrySanityStatus.PASS,
            checks=(
                "SAME_SNAPSHOT_COORDINATES",
                "FINITE_POSITIVE_DEPTH",
                "VALID_CAMERA_INTRINSICS",
                "FINITE_TARGET_POINT_CLOUD",
                "POSITIVE_FORWARD_CENTROID",
            ),
        )

    @staticmethod
    def _validate_snapshot(snapshot: TargetSceneSnapshot) -> None:
        if snapshot.target.source_frame_id != snapshot.frame.frame_id:
            raise ValueError("target source_frame_id does not match Scene Snapshot")
        if snapshot.target.source_timestamp_s != snapshot.frame.timestamp_s:
            raise ValueError("target timestamp does not match Scene Snapshot")
        if snapshot.target.mask.shape != snapshot.frame.rgb.shape[:2]:
            raise ValueError("target mask does not match Scene Snapshot")

    @staticmethod
    def _validate_intrinsics(intrinsics: object) -> None:
        values = np.asarray(
            [
                getattr(intrinsics, "fx", np.nan),
                getattr(intrinsics, "fy", np.nan),
                getattr(intrinsics, "cx", np.nan),
                getattr(intrinsics, "cy", np.nan),
            ],
            dtype=np.float64,
        )
        if not np.all(np.isfinite(values)) or values[0] <= 0.0 or values[1] <= 0.0:
            raise ValueError("camera intrinsics must contain finite positive focal lengths")

    def _depth_inliers(self, depths: NDArray[np.float64]) -> NDArray[np.bool_]:
        median = float(np.median(depths))
        mad = float(np.median(np.abs(depths - median)))
        robust_sigma = 1.4826 * mad
        half_band = max(
            self._config.minimum_depth_band,
            self._config.outlier_mad_scale * robust_sigma,
        )
        return np.asarray(np.abs(depths - median) <= half_band, dtype=np.bool_)

    def _sample_indices(self, point_count: int) -> NDArray[np.int64]:
        if point_count <= self._config.maximum_points:
            return np.arange(point_count, dtype=np.int64)
        return np.linspace(
            0,
            point_count - 1,
            num=self._config.maximum_points,
            dtype=np.int64,
        )

    @staticmethod
    def _result_depth_mode(
        *,
        source: DepthSource,
        native_mode: DepthMode,
        calibration_state: CalibrationState,
    ) -> DepthMode:
        if native_mode is DepthMode.RELATIVE:
            return DepthMode.RELATIVE
        if (
            source is DepthSource.RGBD
            and native_mode is DepthMode.METRIC
            and calibration_state is CalibrationState.CALIBRATED
        ):
            return DepthMode.METRIC
        return DepthMode.APPROX_METRIC

    @staticmethod
    def _emit(
        progress: SpatialProgressCallback | None,
        stage: SpatialStage,
        details: dict[str, object] | None = None,
    ) -> None:
        if progress is not None:
            progress(stage, details)
