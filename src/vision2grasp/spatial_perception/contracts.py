"""Model-neutral contracts for frozen-scene spatial perception."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import CameraIntrinsics


class DepthMode(str, Enum):
    """Scale semantics of a depth or reconstructed spatial result."""

    RELATIVE = "RELATIVE"
    APPROX_METRIC = "APPROX_METRIC"
    METRIC = "METRIC"


class DepthSource(str, Enum):
    MONOCULAR = "MONOCULAR"
    RGBD = "RGBD"


class IntrinsicsSource(str, Enum):
    NOMINAL_FOV = "NOMINAL_FOV"
    CALIBRATED = "CALIBRATED"
    RGBD_NATIVE = "RGBD_NATIVE"


class CalibrationState(str, Enum):
    UNCALIBRATED = "UNCALIBRATED"
    CALIBRATED = "CALIBRATED"


class DepthCalibrationMode(str, Enum):
    NONE = "NONE"
    REFERENCE = "REFERENCE"
    MARKER = "MARKER"
    PLANE_ASSISTANCE = "PLANE_ASSISTANCE"


@dataclass(frozen=True, slots=True)
class IntrinsicsObservation:
    intrinsics: CameraIntrinsics
    source: IntrinsicsSource
    calibration_state: CalibrationState
    depth_calibration_mode: DepthCalibrationMode = DepthCalibrationMode.NONE
    nominal_fov_deg: float | None = None

    def __post_init__(self) -> None:
        if self.nominal_fov_deg is not None:
            if not np.isfinite(self.nominal_fov_deg) or not 1.0 < self.nominal_fov_deg < 179.0:
                raise ValueError("nominal_fov_deg must be finite and in (1, 179)")
        if self.source is IntrinsicsSource.NOMINAL_FOV:
            if self.calibration_state is not CalibrationState.UNCALIBRATED:
                raise ValueError("nominal FOV intrinsics must remain UNCALIBRATED")
            if self.nominal_fov_deg is None:
                raise ValueError("nominal FOV intrinsics require nominal_fov_deg")


@dataclass(frozen=True, slots=True)
class DepthFrame:
    source_frame_id: int
    source_timestamp_s: float
    values: NDArray[np.float32]
    source: DepthSource
    native_mode: DepthMode
    inference_time_s: float = 0.0

    def __post_init__(self) -> None:
        if self.source_frame_id < 0:
            raise ValueError("source_frame_id must be non-negative")
        if not np.isfinite(self.source_timestamp_s):
            raise ValueError("source_timestamp_s must be finite")
        if not np.isfinite(self.inference_time_s) or self.inference_time_s < 0.0:
            raise ValueError("inference_time_s must be finite and non-negative")
        depth = np.asarray(self.values, dtype=np.float32)
        if depth.ndim != 2 or depth.size == 0:
            raise ValueError("depth values must be a non-empty 2D array")
        immutable = np.ascontiguousarray(depth.copy())
        immutable.setflags(write=False)
        object.__setattr__(self, "values", immutable)


@dataclass(frozen=True, slots=True)
class TargetDepth:
    value: float
    valid_ratio: float
    inlier_ratio: float
    valid_pixel_count: int
    inlier_pixel_count: int

    def __post_init__(self) -> None:
        if not np.isfinite(self.value) or self.value <= 0.0:
            raise ValueError("target depth must be finite and positive")
        if not 0.0 <= self.valid_ratio <= 1.0:
            raise ValueError("valid_ratio must be in [0, 1]")
        if not 0.0 <= self.inlier_ratio <= 1.0:
            raise ValueError("inlier_ratio must be in [0, 1]")
        if self.valid_pixel_count <= 0 or self.inlier_pixel_count <= 0:
            raise ValueError("depth pixel counts must be positive")
        if self.inlier_pixel_count > self.valid_pixel_count:
            raise ValueError("inlier pixel count cannot exceed valid pixel count")


@dataclass(frozen=True, slots=True)
class SpatialGeometryDiagnostics:
    """Auditable geometry facts for one frozen SpatialResult.

    These values describe the real tensors and transforms used by the provider;
    they are intentionally API diagnostics rather than prominent Workspace UI.
    """

    snapshot_size: tuple[int, int]
    depth_size: tuple[int, int]
    mask_size: tuple[int, int]
    nominal_hfov_deg: float
    nominal_vfov_deg: float
    target_bbox_pixels: tuple[float, float, float, float]
    target_mask_pixel_count: int
    target_mask_bbox_fill_ratio: float
    target_mask_component_count: int
    target_mask_largest_component_ratio: float
    target_depth_median: float
    point_cloud_extent_xyz: NDArray[np.float64]
    extent_quantiles: tuple[float, float]
    geometry_aligned: bool
    crop_applied: bool = False
    rotation_applied: bool = False

    def __post_init__(self) -> None:
        for name, size in (
            ("snapshot_size", self.snapshot_size),
            ("depth_size", self.depth_size),
            ("mask_size", self.mask_size),
        ):
            if len(size) != 2 or any(int(value) <= 0 for value in size):
                raise ValueError(f"{name} must contain positive width and height")
        if not all(np.isfinite(value) for value in self.target_bbox_pixels):
            raise ValueError("target_bbox_pixels must contain finite values")
        if self.target_mask_pixel_count <= 0 or self.target_mask_component_count <= 0:
            raise ValueError("target mask diagnostics must be positive")
        for value in (
            self.nominal_hfov_deg,
            self.nominal_vfov_deg,
            self.target_mask_bbox_fill_ratio,
            self.target_mask_largest_component_ratio,
            self.target_depth_median,
        ):
            if not np.isfinite(value):
                raise ValueError("spatial geometry diagnostics must be finite")
        if not 0.0 < self.nominal_hfov_deg < 179.0:
            raise ValueError("nominal_hfov_deg must be in (0, 179)")
        if not 0.0 < self.nominal_vfov_deg < 179.0:
            raise ValueError("nominal_vfov_deg must be in (0, 179)")
        if not 0.0 < self.target_mask_bbox_fill_ratio <= 1.0:
            raise ValueError("target_mask_bbox_fill_ratio must be in (0, 1]")
        if not 0.0 < self.target_mask_largest_component_ratio <= 1.0:
            raise ValueError("target_mask_largest_component_ratio must be in (0, 1]")
        lower, upper = self.extent_quantiles
        if not 0.0 <= lower < upper <= 1.0:
            raise ValueError("extent_quantiles must be ordered inside [0, 1]")
        extent = np.asarray(self.point_cloud_extent_xyz, dtype=np.float64)
        if extent.shape != (3,) or not np.all(np.isfinite(extent)) or np.any(extent < 0.0):
            raise ValueError("point_cloud_extent_xyz must be a finite non-negative 3-vector")
        immutable_extent = np.ascontiguousarray(extent.copy())
        immutable_extent.setflags(write=False)
        object.__setattr__(self, "point_cloud_extent_xyz", immutable_extent)

    def public_metadata(self) -> dict[str, object]:
        x1, y1, x2, y2 = self.target_bbox_pixels
        return {
            "snapshot_size": {"width": self.snapshot_size[0], "height": self.snapshot_size[1]},
            "depth_size": {"width": self.depth_size[0], "height": self.depth_size[1]},
            "mask_size": {"width": self.mask_size[0], "height": self.mask_size[1]},
            "nominal_hfov_deg": self.nominal_hfov_deg,
            "nominal_vfov_deg": self.nominal_vfov_deg,
            "target_bbox_pixels": {
                "xyxy": [x1, y1, x2, y2],
                "width": x2 - x1,
                "height": y2 - y1,
            },
            "target_mask_pixel_count": self.target_mask_pixel_count,
            "target_mask_bbox_fill_ratio": self.target_mask_bbox_fill_ratio,
            "target_mask_component_count": self.target_mask_component_count,
            "target_mask_largest_component_ratio": self.target_mask_largest_component_ratio,
            "target_depth_median": self.target_depth_median,
            "point_cloud_extent_xyz": self.point_cloud_extent_xyz.tolist(),
            "point_cloud_extent_quantiles": list(self.extent_quantiles),
            "geometry_aligned": self.geometry_aligned,
            "resize_policy": "DEPTH_POSTPROCESSED_TO_SNAPSHOT",
            "crop_applied": self.crop_applied,
            "rotation_applied": self.rotation_applied,
        }


@dataclass(frozen=True, slots=True)
class SpatialObservation:
    """Backend-independent target geometry in the OpenCV camera frame.

    Camera convention: +X right, +Y down, +Z forward. No robot or world
    transform is implied by this contract.
    """

    snapshot_id: str
    source_frame_id: int
    target_instance_id: str
    source_timestamp_s: float
    depth_frame: DepthFrame
    target_depth: TargetDepth
    centroid_xyz: NDArray[np.float64]
    target_point_cloud: NDArray[np.float32]
    camera_intrinsics: IntrinsicsObservation
    depth_source: DepthSource
    depth_mode: DepthMode
    inference_time_s: float
    geometry_diagnostics: SpatialGeometryDiagnostics | None = None

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.target_instance_id.strip():
            raise ValueError("snapshot and target identifiers must not be empty")
        if self.source_frame_id != self.depth_frame.source_frame_id:
            raise ValueError("depth frame does not match SpatialObservation frame")
        if self.source_timestamp_s != self.depth_frame.source_timestamp_s:
            raise ValueError("depth frame timestamp does not match SpatialObservation")
        centroid = np.asarray(self.centroid_xyz, dtype=np.float64)
        points = np.asarray(self.target_point_cloud, dtype=np.float32)
        if centroid.shape != (3,) or not np.all(np.isfinite(centroid)):
            raise ValueError("centroid_xyz must be a finite 3-vector")
        if points.ndim != 2 or points.shape[1:] != (3,) or points.shape[0] == 0:
            raise ValueError("target_point_cloud must have shape (N, 3) with N > 0")
        if not np.all(np.isfinite(points)):
            raise ValueError("target_point_cloud must contain only finite values")
        if not np.isfinite(self.inference_time_s) or self.inference_time_s < 0.0:
            raise ValueError("inference_time_s must be finite and non-negative")
        immutable_centroid = np.ascontiguousarray(centroid.copy())
        immutable_centroid.setflags(write=False)
        immutable_points = np.ascontiguousarray(points.copy())
        immutable_points.setflags(write=False)
        object.__setattr__(self, "centroid_xyz", immutable_centroid)
        object.__setattr__(self, "target_point_cloud", immutable_points)

    @property
    def unit(self) -> str:
        return "m" if self.depth_mode in {DepthMode.APPROX_METRIC, DepthMode.METRIC} else "relative"

    def public_metadata(self) -> dict[str, object]:
        intrinsics = self.camera_intrinsics.intrinsics
        return {
            "snapshot_id": self.snapshot_id,
            "source_frame_id": self.source_frame_id,
            "target_instance_id": self.target_instance_id,
            "source_timestamp_s": self.source_timestamp_s,
            "target_depth": self.target_depth.value,
            "centroid_xyz": self.centroid_xyz.tolist(),
            "point_count": int(self.target_point_cloud.shape[0]),
            "depth_source": self.depth_source.value,
            "depth_mode": self.depth_mode.value,
            "unit": self.unit,
            "camera_frame": "OPENCV_CAMERA_X_RIGHT_Y_DOWN_Z_FORWARD",
            "intrinsics_source": self.camera_intrinsics.source.value,
            "calibration_state": self.camera_intrinsics.calibration_state.value,
            "depth_calibration_mode": self.camera_intrinsics.depth_calibration_mode.value,
            "scale_mode": (
                "DIRECT"
                if self.camera_intrinsics.depth_calibration_mode is DepthCalibrationMode.NONE
                else "ASSISTED"
            ),
            "nominal_fov_deg": self.camera_intrinsics.nominal_fov_deg,
            "camera_intrinsics": {
                "width": intrinsics.width,
                "height": intrinsics.height,
                "fx": intrinsics.fx,
                "fy": intrinsics.fy,
                "cx": intrinsics.cx,
                "cy": intrinsics.cy,
            },
            "quality": {
                "valid_depth_ratio": self.target_depth.valid_ratio,
                "inlier_ratio": self.target_depth.inlier_ratio,
                "valid_pixel_count": self.target_depth.valid_pixel_count,
                "inlier_pixel_count": self.target_depth.inlier_pixel_count,
            },
            "inference_time_s": self.inference_time_s,
            "geometry_diagnostics": (
                None
                if self.geometry_diagnostics is None
                else self.geometry_diagnostics.public_metadata()
            ),
        }
