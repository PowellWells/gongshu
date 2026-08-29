"""Contracts for geometry-driven grasp planning in Gongshu v0.6."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vision2grasp.spatial_perception import (
    CalibrationState,
    DepthMode,
    IntrinsicsSource,
)


GRASP_PLAN_SCHEMA_VERSION = "gongshu.grasp-plan/v1"


class PlanningState(str, Enum):
    WAITING = "WAITING"
    PLANNING = "PLANNING"
    READY = "READY"
    FAILED = "FAILED"


class ConfidenceType(str, Enum):
    HEURISTIC_UNCALIBRATED = "HEURISTIC_UNCALIBRATED"


@dataclass(frozen=True, slots=True)
class GraspConfidence:
    """Uncalibrated geometry-quality evidence, never a success probability."""

    value: float
    factors: dict[str, float]
    type: ConfidenceType = ConfidenceType.HEURISTIC_UNCALIBRATED

    def __post_init__(self) -> None:
        required = {"point_support", "depth_validity", "pca_stability", "width_margin"}
        if set(self.factors) != required:
            raise ValueError(f"confidence factors must be exactly {sorted(required)}")
        if not np.isfinite(self.value) or not 0.0 <= self.value <= 1.0:
            raise ValueError("confidence value must be finite and in [0, 1]")
        for name, value in self.factors.items():
            if not np.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"confidence factor {name} must be in [0, 1]")
        object.__setattr__(self, "factors", dict(self.factors))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "type": self.type.value,
            "factors": dict(self.factors),
        }


@dataclass(frozen=True, slots=True)
class GraspCandidate:
    candidate_id: str
    grasp_point_xyz: NDArray[np.float64]
    approach_vector: NDArray[np.float64]
    closing_vector: NDArray[np.float64]
    grasp_angle: float
    gripper_width: float
    quality_score: float
    score_factors: dict[str, float]

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        for name in ("grasp_point_xyz", "approach_vector", "closing_vector"):
            value = np.asarray(getattr(self, name), dtype=np.float64)
            if value.shape != (3,) or not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must be a finite 3-vector")
            if name != "grasp_point_xyz":
                norm = float(np.linalg.norm(value))
                if not np.isclose(norm, 1.0, atol=1e-6):
                    raise ValueError(f"{name} must be a unit vector")
            immutable = np.ascontiguousarray(value.copy())
            immutable.setflags(write=False)
            object.__setattr__(self, name, immutable)
        if not np.isfinite(self.grasp_angle):
            raise ValueError("grasp_angle must be finite")
        if not np.isfinite(self.gripper_width) or self.gripper_width <= 0.0:
            raise ValueError("gripper_width must be finite and positive")
        if not np.isfinite(self.quality_score) or not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score must be in [0, 1]")
        object.__setattr__(self, "score_factors", dict(self.score_factors))


@dataclass(frozen=True, slots=True)
class GraspPlan:
    """One selected camera-frame plan with explicit scale uncertainty."""

    target_id: str
    snapshot_id: str
    source_frame_id: int
    grasp_point_xyz: NDArray[np.float64]
    approach_vector: NDArray[np.float64]
    closing_vector: NDArray[np.float64]
    grasp_angle: float
    gripper_width: float
    quality_score: float
    confidence: GraspConfidence
    source: str
    coordinate_frame: str
    depth_mode: DepthMode
    planning_state: PlanningState
    intrinsics_source: IntrinsicsSource
    calibration_state: CalibrationState
    uncertainty: tuple[str, ...]
    object_extents_xyz: NDArray[np.float64]
    candidate_count: int

    def __post_init__(self) -> None:
        if not self.target_id.strip() or not self.snapshot_id.strip():
            raise ValueError("target_id and snapshot_id must not be empty")
        if self.source_frame_id < 0:
            raise ValueError("source_frame_id must be non-negative")
        if self.planning_state is not PlanningState.READY:
            raise ValueError("serialized GraspPlan must be READY")
        if not self.source.strip() or not self.coordinate_frame.strip():
            raise ValueError("source and coordinate_frame must not be empty")
        if self.candidate_count < 1:
            raise ValueError("candidate_count must be positive")
        if not np.isfinite(self.grasp_angle):
            raise ValueError("grasp_angle must be finite")
        if not np.isfinite(self.gripper_width) or self.gripper_width <= 0.0:
            raise ValueError("gripper_width must be positive")
        if not np.isfinite(self.quality_score) or not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("quality_score must be in [0, 1]")
        for name in ("grasp_point_xyz", "approach_vector", "closing_vector", "object_extents_xyz"):
            value = np.asarray(getattr(self, name), dtype=np.float64)
            if value.shape != (3,) or not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must be a finite 3-vector")
            if name in {"approach_vector", "closing_vector"} and not np.isclose(
                np.linalg.norm(value), 1.0, atol=1e-6
            ):
                raise ValueError(f"{name} must be a unit vector")
            if name == "object_extents_xyz" and np.any(value <= 0.0):
                raise ValueError("object_extents_xyz must be positive")
            immutable = np.ascontiguousarray(value.copy())
            immutable.setflags(write=False)
            object.__setattr__(self, name, immutable)
        object.__setattr__(self, "uncertainty", tuple(dict.fromkeys(self.uncertainty)))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": GRASP_PLAN_SCHEMA_VERSION,
            "target_id": self.target_id,
            "snapshot_id": self.snapshot_id,
            "source_frame_id": self.source_frame_id,
            "grasp_point_xyz": self.grasp_point_xyz.tolist(),
            "approach_vector": self.approach_vector.tolist(),
            "closing_vector": self.closing_vector.tolist(),
            "grasp_angle": self.grasp_angle,
            "grasp_angle_deg": float(np.degrees(self.grasp_angle)),
            "gripper_width": self.gripper_width,
            "quality_score": self.quality_score,
            "confidence": self.confidence.public_metadata(),
            "source": self.source,
            "coordinate_frame": self.coordinate_frame,
            "depth_mode": self.depth_mode.value,
            "planning_state": self.planning_state.value,
            "intrinsics_source": self.intrinsics_source.value,
            "calibration_state": self.calibration_state.value,
            "uncertainty": list(self.uncertainty),
            "object_extents_xyz": self.object_extents_xyz.tolist(),
            "candidate_count": self.candidate_count,
            "execution_scope": "SIMULATION_ONLY",
        }

