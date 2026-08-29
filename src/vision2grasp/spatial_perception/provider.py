"""Mask-aware depth statistics and camera-frame backprojection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import (
    CalibrationState,
    DepthMode,
    DepthSource,
    SpatialObservation,
    TargetDepth,
)
from .interfaces import CameraIntrinsicsProvider, DepthProvider


@dataclass(frozen=True, slots=True)
class MaskSpatialPerceptionConfig:
    minimum_valid_depth_ratio: float = 0.50
    minimum_points: int = 30
    maximum_points: int = 4096
    outlier_mad_scale: float = 3.5
    minimum_depth_band: float = 0.02

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_valid_depth_ratio <= 1.0:
            raise ValueError("minimum_valid_depth_ratio must be in (0, 1]")
        if self.minimum_points <= 0:
            raise ValueError("minimum_points must be positive")
        if self.maximum_points < self.minimum_points:
            raise ValueError("maximum_points must be at least minimum_points")
        if self.outlier_mad_scale <= 0.0 or self.minimum_depth_band <= 0.0:
            raise ValueError("depth filtering parameters must be positive")


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

    def analyze(self, snapshot: TargetSceneSnapshot) -> SpatialObservation:
        frame = snapshot.frame
        target = snapshot.target
        self._validate_snapshot(snapshot)
        depth_frame = self._depth_provider.infer(frame)
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
        return SpatialObservation(
            snapshot_id=snapshot.snapshot_id,
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
