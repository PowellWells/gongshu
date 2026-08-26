"""Typed objects exchanged between independent pipeline modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

import numpy as np
from numpy.typing import NDArray


def _require_shape(name: str, value: NDArray[np.generic], shape: tuple[int, ...]) -> None:
    if value.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {value.shape}")


@dataclass(frozen=True, slots=True)
class CameraIntrinsics:
    """Pinhole camera intrinsics in pixel units."""

    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Camera dimensions must be positive")
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("Camera focal lengths must be positive")


@dataclass(frozen=True, slots=True)
class RGBFrame:
    """One RGB observation from a real camera or image file.

    This contract deliberately carries no depth or metric camera pose. Real RGB
    input must not be disguised as an RGB-D observation.
    """

    frame_id: int
    timestamp_s: float
    camera_name: str
    rgb: NDArray[np.uint8]

    def __post_init__(self) -> None:
        if self.frame_id < 0:
            raise ValueError("frame_id must be non-negative")
        if not np.isfinite(self.timestamp_s):
            raise ValueError("timestamp_s must be finite")
        if not self.camera_name.strip():
            raise ValueError("camera_name must not be empty")
        if self.rgb.ndim != 3 or self.rgb.shape[2] != 3:
            raise ValueError("rgb must have shape (H, W, 3)")
        if self.rgb.shape[0] <= 0 or self.rgb.shape[1] <= 0:
            raise ValueError("rgb dimensions must be positive")
        if self.rgb.dtype != np.uint8:
            raise ValueError(f"rgb must use uint8, got {self.rgb.dtype}")


@dataclass(frozen=True, slots=True)
class RGBDFrame:
    """Synchronized RGB-D observation with camera calibration."""

    frame_id: int
    timestamp_s: float
    camera_name: str
    rgb: NDArray[np.uint8]
    depth_m: NDArray[np.float32]
    intrinsics: CameraIntrinsics
    world_from_camera: NDArray[np.float64]

    def __post_init__(self) -> None:
        expected_rgb = (self.intrinsics.height, self.intrinsics.width, 3)
        expected_depth = (self.intrinsics.height, self.intrinsics.width)
        _require_shape("rgb", self.rgb, expected_rgb)
        _require_shape("depth_m", self.depth_m, expected_depth)
        _require_shape("world_from_camera", self.world_from_camera, (4, 4))
        if self.rgb.dtype != np.uint8:
            raise ValueError(f"rgb must use uint8, got {self.rgb.dtype}")
        if not np.issubdtype(self.depth_m.dtype, np.floating):
            raise ValueError(f"depth_m must use a floating dtype, got {self.depth_m.dtype}")


@dataclass(frozen=True, slots=True)
class Detection2D:
    """One instance-segmentation result in original image coordinates."""

    class_id: int
    class_name: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]
    mask: NDArray[np.bool_]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        x1, y1, x2, y2 = self.bbox_xyxy
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bbox_xyxy must have positive width and height")
        if self.mask.ndim != 2 or self.mask.dtype != np.bool_:
            raise ValueError("mask must be a 2D boolean array")


@dataclass(frozen=True, slots=True)
class LocalizedTarget:
    """Perception-derived target geometry in world coordinates."""

    detection: Detection2D
    centroid_world_m: NDArray[np.float64]
    points_world_m: NDArray[np.float64]
    depth_valid_ratio: float

    def __post_init__(self) -> None:
        _require_shape("centroid_world_m", self.centroid_world_m, (3,))
        if self.points_world_m.ndim != 2 or self.points_world_m.shape[1] != 3:
            raise ValueError("points_world_m must have shape (N, 3)")
        if not 0.0 <= self.depth_valid_ratio <= 1.0:
            raise ValueError("depth_valid_ratio must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class TableCalibration:
    """Manual four-point mapping between image pixels and a measured table plane."""

    image_width: int
    image_height: int
    table_width_m: float
    table_height_m: float
    image_points_px: NDArray[np.float64]
    table_from_image: NDArray[np.float64]
    image_from_table: NDArray[np.float64]
    image_coverage_ratio: float

    def __post_init__(self) -> None:
        if self.image_width <= 0 or self.image_height <= 0:
            raise ValueError("calibration image dimensions must be positive")
        if self.table_width_m <= 0.0 or self.table_height_m <= 0.0:
            raise ValueError("measured table dimensions must be positive")
        _require_shape("image_points_px", self.image_points_px, (4, 2))
        _require_shape("table_from_image", self.table_from_image, (3, 3))
        _require_shape("image_from_table", self.image_from_table, (3, 3))
        for name, value in (
            ("image_points_px", self.image_points_px),
            ("table_from_image", self.table_from_image),
            ("image_from_table", self.image_from_table),
        ):
            if not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must contain only finite values")
        if not 0.0 < self.image_coverage_ratio <= 1.0:
            raise ValueError("image_coverage_ratio must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class PlanarLocalizedTarget:
    """Bottle geometry estimated on a manually calibrated tabletop plane."""

    detection: Detection2D
    center_image_px: NDArray[np.float64]
    center_table_m: NDArray[np.float64]
    points_table_m: NDArray[np.float64]
    principal_yaw_rad: float
    estimated_width_m: float
    estimated_length_m: float
    circularity: float

    def __post_init__(self) -> None:
        _require_shape("center_image_px", self.center_image_px, (2,))
        _require_shape("center_table_m", self.center_table_m, (2,))
        if self.points_table_m.ndim != 2 or self.points_table_m.shape[1] != 2:
            raise ValueError("points_table_m must have shape (N, 2)")
        if self.points_table_m.shape[0] < 3:
            raise ValueError("points_table_m must contain at least three points")
        if not np.all(np.isfinite(self.center_image_px)) or not np.all(
            np.isfinite(self.center_table_m)
        ) or not np.all(np.isfinite(self.points_table_m)):
            raise ValueError("planar target geometry must contain only finite values")
        if not np.isfinite(self.principal_yaw_rad):
            raise ValueError("principal_yaw_rad must be finite")
        if self.estimated_width_m <= 0.0 or self.estimated_length_m <= 0.0:
            raise ValueError("estimated planar extents must be positive")
        if not 0.0 <= self.circularity <= 1.0:
            raise ValueError("circularity must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PlanarGraspCandidate:
    """Explainable top-grasp candidate estimated from a real RGB mask."""

    candidate_id: str
    center_table_m: NDArray[np.float64]
    yaw_rad: float
    estimated_gripper_width_m: float
    vision_score: float
    geometry_score: float
    final_score: float
    width_feasible: bool
    score_terms: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("candidate_id must not be empty")
        _require_shape("center_table_m", self.center_table_m, (2,))
        if not np.all(np.isfinite(self.center_table_m)) or not np.isfinite(
            self.yaw_rad
        ):
            raise ValueError("candidate pose must contain only finite values")
        if self.estimated_gripper_width_m <= 0.0:
            raise ValueError("estimated_gripper_width_m must be positive")
        for name, value in (
            ("vision_score", self.vision_score),
            ("geometry_score", self.geometry_score),
            ("final_score", self.final_score),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class GraspCandidate:
    """A scored top-grasp pose expressed in world coordinates."""

    candidate_id: str
    world_from_grasp: NDArray[np.float64]
    gripper_width_m: float
    score: float
    reachable: bool
    score_terms: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_shape("world_from_grasp", self.world_from_grasp, (4, 4))
        if self.gripper_width_m <= 0:
            raise ValueError("gripper_width_m must be positive")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PandaProprioception:
    """Robot-only state available to deterministic grasp control.

    ``world_from_eef`` describes robosuite's end-effector *site*, not the
    similarly named body orientation. Object pose, contact and task-success
    truth deliberately do not belong to this contract.
    """

    timestamp_s: float
    world_from_eef: NDArray[np.float64]
    gripper_qpos: NDArray[np.float64]

    def __post_init__(self) -> None:
        _require_shape("world_from_eef", self.world_from_eef, (4, 4))
        if self.gripper_qpos.ndim != 1 or self.gripper_qpos.size == 0:
            raise ValueError("gripper_qpos must be a non-empty 1D array")
        if not np.isfinite(self.timestamp_s):
            raise ValueError("timestamp_s must be finite")
        if not np.all(np.isfinite(self.world_from_eef)):
            raise ValueError("world_from_eef must contain only finite values")
        if not np.all(np.isfinite(self.gripper_qpos)):
            raise ValueError("gripper_qpos must contain only finite values")

        rotation = self.world_from_eef[:3, :3]
        if not np.allclose(self.world_from_eef[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8):
            raise ValueError("world_from_eef must have a rigid homogeneous bottom row")
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6):
            raise ValueError("world_from_eef rotation must be orthonormal")
        if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6):
            raise ValueError("world_from_eef rotation must have determinant +1")


class ExecutionPhase(str, Enum):
    HOME = "HOME"
    PREGRASP = "PREGRASP"
    DESCEND = "DESCEND"
    CLOSE = "CLOSE"
    LIFT = "LIFT"
    RETURN_HOME = "RETURN_HOME"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Final result emitted by the deterministic Panda state machine."""

    candidate_id: str
    success: bool
    final_phase: ExecutionPhase
    message: str
    visited_phases: tuple[ExecutionPhase, ...]

    def __post_init__(self) -> None:
        expected = ExecutionPhase.SUCCEEDED if self.success else ExecutionPhase.FAILED
        if self.final_phase is not expected:
            raise ValueError(f"final_phase must be {expected.value} when success={self.success}")
