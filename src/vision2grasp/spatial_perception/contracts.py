"""Model-neutral contracts for frozen-scene spatial perception."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from numpy.typing import NDArray

from vision2grasp.condition_processing import (
    ConditionReport,
    PerceptionUncertainty,
    SpatialUncertainty,
)

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
    CALIBRATED = "CALIBRATED"
    SENSOR_METADATA = "SENSOR_METADATA"
    MODEL_PREDICTED = "MODEL_PREDICTED"
    NOMINAL_FOV = "NOMINAL_FOV"
    RGBD_NATIVE = "RGBD_NATIVE"


class CalibrationState(str, Enum):
    UNCALIBRATED = "UNCALIBRATED"
    CALIBRATED = "CALIBRATED"


class DepthCalibrationMode(str, Enum):
    NONE = "NONE"
    REFERENCE = "REFERENCE"
    MARKER = "MARKER"
    PLANE_ASSISTANCE = "PLANE_ASSISTANCE"


class SpatialStage(str, Enum):
    QUEUED = "QUEUED"
    SCENE_PREPARING = "SCENE_PREPARING"
    MODEL_RESOLVING = "MODEL_RESOLVING"
    MODEL_DOWNLOADING = "MODEL_DOWNLOADING"
    CHECKSUM_VERIFYING = "CHECKSUM_VERIFYING"
    MODEL_LOADING = "MODEL_LOADING"
    DEPTH_INFERENCE = "DEPTH_INFERENCE"
    POINT_CLOUD_BUILDING = "POINT_CLOUD_BUILDING"
    SPATIAL_COMPUTING = "SPATIAL_COMPUTING"
    READY = "READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    # Compatibility aliases for the v0.5 pre-job API.
    DEPTH_ESTIMATING = "DEPTH_INFERENCE"
    ERROR = "FAILED"


class GeometrySanityStatus(str, Enum):
    PASS = "PASS"
    REJECTED = "REJECTED"


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
    model_load_time_s: float = 0.0
    model_was_ready: bool = False
    model_input_size: tuple[int, int] | None = None
    model_location: str | None = None
    resize_policy: str = "MODEL_RESIZE_THEN_DEPTH_TO_SNAPSHOT"

    def __post_init__(self) -> None:
        if self.source_frame_id < 0:
            raise ValueError("source_frame_id must be non-negative")
        if not np.isfinite(self.source_timestamp_s):
            raise ValueError("source_timestamp_s must be finite")
        for name, value in (
            ("inference_time_s", self.inference_time_s),
            ("model_load_time_s", self.model_load_time_s),
        ):
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if self.model_input_size is not None:
            if len(self.model_input_size) != 2 or any(
                int(value) <= 0 for value in self.model_input_size
            ):
                raise ValueError("model_input_size must contain positive width and height")
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
class GeometrySanity:
    status: GeometrySanityStatus
    checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.checks or any(not check.strip() for check in self.checks):
            raise ValueError("geometry sanity checks must not be empty")
        object.__setattr__(self, "checks", tuple(dict.fromkeys(self.checks)))

    def public_metadata(self) -> dict[str, object]:
        return {"status": self.status.value, "checks": list(self.checks)}


@dataclass(frozen=True, slots=True)
class SpatialGeometryDiagnostics:
    """Auditable geometry facts for one frozen SpatialResult.

    These values describe the real tensors and transforms used by the provider;
    they are intentionally API diagnostics rather than prominent Workspace UI.
    """

    snapshot_size: tuple[int, int]
    depth_size: tuple[int, int]
    mask_size: tuple[int, int]
    model_input_size: tuple[int, int] | None
    geometry_chain_id: str
    fx: float
    fy: float
    cx: float
    cy: float
    intrinsics_source: IntrinsicsSource
    calibration_state: CalibrationState
    depth_mode: DepthMode
    nominal_hfov_deg: float
    nominal_vfov_deg: float
    target_bbox_pixels: tuple[float, float, float, float]
    target_mask_pixel_count: int
    target_mask_bbox_fill_ratio: float
    target_mask_component_count: int
    target_mask_largest_component_ratio: float
    target_depth_median: float
    valid_depth_ratio: float
    point_cloud_extent_xyz: NDArray[np.float64]
    target_centroid_xyz: NDArray[np.float64]
    extent_quantiles: tuple[float, float]
    geometry_aligned: bool
    crop_applied: bool = False
    rotation_applied: bool = False
    letterbox_applied: bool = False
    display_object_fit: str = "contain"
    depth_resize_policy: str = "MODEL_RESIZE_THEN_DEPTH_TO_SNAPSHOT"

    def __post_init__(self) -> None:
        for name, size in (
            ("snapshot_size", self.snapshot_size),
            ("depth_size", self.depth_size),
            ("mask_size", self.mask_size),
        ):
            if len(size) != 2 or any(int(value) <= 0 for value in size):
                raise ValueError(f"{name} must contain positive width and height")
        if self.model_input_size is not None and (
            len(self.model_input_size) != 2
            or any(int(value) <= 0 for value in self.model_input_size)
        ):
            raise ValueError("model_input_size must contain positive width and height")
        if not self.geometry_chain_id.strip():
            raise ValueError("geometry_chain_id must not be empty")
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
            self.fx,
            self.fy,
            self.cx,
            self.cy,
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
        if not 0.0 <= self.valid_depth_ratio <= 1.0:
            raise ValueError("valid_depth_ratio must be in [0, 1]")
        if self.fx <= 0.0 or self.fy <= 0.0:
            raise ValueError("diagnostic focal lengths must be positive")
        lower, upper = self.extent_quantiles
        if not 0.0 <= lower < upper <= 1.0:
            raise ValueError("extent_quantiles must be ordered inside [0, 1]")
        extent = np.asarray(self.point_cloud_extent_xyz, dtype=np.float64)
        if extent.shape != (3,) or not np.all(np.isfinite(extent)) or np.any(extent < 0.0):
            raise ValueError("point_cloud_extent_xyz must be a finite non-negative 3-vector")
        immutable_extent = np.ascontiguousarray(extent.copy())
        immutable_extent.setflags(write=False)
        object.__setattr__(self, "point_cloud_extent_xyz", immutable_extent)
        centroid = np.asarray(self.target_centroid_xyz, dtype=np.float64)
        if centroid.shape != (3,) or not np.all(np.isfinite(centroid)):
            raise ValueError("target_centroid_xyz must be a finite 3-vector")
        immutable_centroid = np.ascontiguousarray(centroid.copy())
        immutable_centroid.setflags(write=False)
        object.__setattr__(self, "target_centroid_xyz", immutable_centroid)

    def public_metadata(self) -> dict[str, object]:
        x1, y1, x2, y2 = self.target_bbox_pixels
        return {
            "snapshot_size": {"width": self.snapshot_size[0], "height": self.snapshot_size[1]},
            "depth_size": {"width": self.depth_size[0], "height": self.depth_size[1]},
            "mask_size": {"width": self.mask_size[0], "height": self.mask_size[1]},
            "model_input_size": (
                None
                if self.model_input_size is None
                else {"width": self.model_input_size[0], "height": self.model_input_size[1]}
            ),
            "geometry_chain_id": self.geometry_chain_id,
            "fx": self.fx,
            "fy": self.fy,
            "cx": self.cx,
            "cy": self.cy,
            "intrinsics_source": self.intrinsics_source.value,
            "calibration_state": self.calibration_state.value,
            "depth_mode": self.depth_mode.value,
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
            "valid_depth_ratio": self.valid_depth_ratio,
            "point_cloud_extent_xyz": self.point_cloud_extent_xyz.tolist(),
            "target_centroid_xyz": self.target_centroid_xyz.tolist(),
            "point_cloud_extent_quantiles": list(self.extent_quantiles),
            "geometry_aligned": self.geometry_aligned,
            "resize_policy": self.depth_resize_policy,
            "crop_applied": self.crop_applied,
            "rotation_applied": self.rotation_applied,
            "letterbox_applied": self.letterbox_applied,
            "display_object_fit": self.display_object_fit,
            "mask_transform": "IDENTITY_IN_SNAPSHOT_PIXELS",
            "intrinsics_coordinate_system": "SNAPSHOT_PIXELS",
            "back_projection": "PERSPECTIVE_CAMERA_FRAME",
        }


@dataclass(frozen=True, slots=True)
class SpatialObservation:
    """Backend-independent target geometry in the OpenCV camera frame.

    Camera convention: +X right, +Y down, +Z forward. No robot or world
    transform is implied by this contract.
    """

    snapshot_id: str
    geometry_chain_id: str
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
    geometry_sanity: GeometrySanity
    geometry_diagnostics: SpatialGeometryDiagnostics | None = None
    condition_report: ConditionReport | None = None
    perception_uncertainty: PerceptionUncertainty | None = None
    spatial_uncertainty: SpatialUncertainty | None = None

    def __post_init__(self) -> None:
        if (
            not self.snapshot_id.strip()
            or not self.geometry_chain_id.strip()
            or not self.target_instance_id.strip()
        ):
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
            "geometry_chain_id": self.geometry_chain_id,
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
            "model_timing": {
                "model_load_s": self.depth_frame.model_load_time_s,
                "depth_inference_s": self.depth_frame.inference_time_s,
                "model_was_ready": self.depth_frame.model_was_ready,
                "model_location": self.depth_frame.model_location,
            },
            "geometry_sanity": self.geometry_sanity.public_metadata(),
            "geometry_diagnostics": (
                None
                if self.geometry_diagnostics is None
                else self.geometry_diagnostics.public_metadata()
            ),
            "condition_report": (
                None if self.condition_report is None else self.condition_report.public_metadata()
            ),
            "perception_uncertainty": (
                None
                if self.perception_uncertainty is None
                else self.perception_uncertainty.public_metadata()
            ),
            "spatial_uncertainty": (
                None
                if self.spatial_uncertainty is None
                else self.spatial_uncertainty.public_metadata()
            ),
        }
