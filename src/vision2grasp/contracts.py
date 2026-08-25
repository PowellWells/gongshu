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
