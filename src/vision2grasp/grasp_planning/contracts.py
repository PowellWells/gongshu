"""Public contracts for target-aware Top-K grasp planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vision2grasp.spatial_perception import CalibrationState, DepthMode, IntrinsicsSource
from vision2grasp.condition_processing import (
    ConditionReport,
    GraspUncertainty,
    PerceptionUncertainty,
    SpatialUncertainty,
)


GRASP_PLAN_SCHEMA_VERSION = "gongshu.grasp-plan/v2"


class PlanningState(str, Enum):
    WAITING = "WAITING"
    PLANNING = "PLANNING"
    GRASP_READY = "GRASP_READY"
    PLANNING_REJECTED = "PLANNING_REJECTED"
    GRASP_ERROR = "GRASP_ERROR"
    READY = "GRASP_READY"
    FAILED = "GRASP_ERROR"


class PlanningMode(str, Enum):
    RESEARCH = "RESEARCH"
    DEMO = "DEMO"


class GraspStage(str, Enum):
    WAITING = "WAITING"
    QUEUED = "QUEUED"
    MODEL_RESOLVING = "MODEL_RESOLVING"
    MODEL_DOWNLOADING = "MODEL_DOWNLOADING"
    CHECKSUM_VERIFYING = "CHECKSUM_VERIFYING"
    MODEL_LOADING = "MODEL_LOADING"
    GRASP_INFERENCE = "GRASP_INFERENCE"
    CANDIDATE_EXTRACTION = "CANDIDATE_EXTRACTION"
    FEASIBILITY_FILTERING = "FEASIBILITY_FILTERING"
    CANDIDATE_RANKING = "CANDIDATE_RANKING"
    GRASP_READY = "GRASP_READY"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CandidateFeasibility(str, Enum):
    EXECUTABLE = "EXECUTABLE"
    REJECTED = "REJECTED"


class ReachabilityState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class CollisionState(str, Enum):
    CLEAR = "CLEAR"
    COLLISION = "COLLISION"
    UNKNOWN = "UNKNOWN"


class ConfidenceType(str, Enum):
    HEURISTIC_UNCALIBRATED = "HEURISTIC_UNCALIBRATED"


@dataclass(frozen=True, slots=True)
class GraspConfidence:
    """Transparent geometry evidence, never a success probability."""

    value: float
    factors: dict[str, float]
    type: ConfidenceType = ConfidenceType.HEURISTIC_UNCALIBRATED

    def __post_init__(self) -> None:
        if not self.factors:
            raise ValueError("confidence factors must not be empty")
        if not np.isfinite(self.value) or not 0.0 <= self.value <= 1.0:
            raise ValueError("confidence value must be finite and in [0, 1]")
        for name, value in self.factors.items():
            if not name.strip() or not np.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"confidence factor {name} must be in [0, 1]")
        object.__setattr__(self, "factors", dict(self.factors))

    def public_metadata(self) -> dict[str, Any]:
        return {"value": self.value, "type": self.type.value, "factors": dict(self.factors)}


@dataclass(frozen=True, slots=True)
class GraspCandidate:
    """One real map-derived antipodal grasp and its feasibility evidence."""

    candidate_id: str
    grasp_point_xyz: NDArray[np.float64]
    approach_vector: NDArray[np.float64]
    closing_vector: NDArray[np.float64]
    grasp_angle: float
    gripper_width: float
    quality_score: float
    score_factors: dict[str, float]
    center_uv: tuple[float, float] | None = None
    width_px: float | None = None
    ranking_score: float = 0.0
    feasibility: CandidateFeasibility = CandidateFeasibility.EXECUTABLE
    rejection_reasons: tuple[str, ...] = ()
    source_frame_id: int = -1
    target_instance_id: str = ""
    target_mask_margin_px: float = 0.0
    valid_depth_ratio: float = 0.0
    width_compatibility: float = 0.0
    reachability: ReachabilityState = ReachabilityState.UNKNOWN
    collision_feasibility: CollisionState = CollisionState.UNKNOWN
    geometry_confidence: float = 0.0

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("candidate_id must not be empty")
        for name in ("grasp_point_xyz", "approach_vector", "closing_vector"):
            value = np.asarray(getattr(self, name), dtype=np.float64)
            if value.shape != (3,) or not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must be a finite 3-vector")
            if name != "grasp_point_xyz" and not np.isclose(np.linalg.norm(value), 1.0, atol=1e-6):
                raise ValueError(f"{name} must be a unit vector")
            immutable = np.ascontiguousarray(value.copy())
            immutable.setflags(write=False)
            object.__setattr__(self, name, immutable)
        if not np.isfinite(self.grasp_angle):
            raise ValueError("grasp_angle must be finite")
        if not np.isfinite(self.gripper_width) or self.gripper_width <= 0.0:
            raise ValueError("gripper_width must be finite and positive")
        for name in (
            "quality_score",
            "ranking_score",
            "valid_depth_ratio",
            "width_compatibility",
            "geometry_confidence",
        ):
            value = float(getattr(self, name))
            if not np.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.center_uv is not None:
            if len(self.center_uv) != 2 or not all(np.isfinite(value) for value in self.center_uv):
                raise ValueError("center_uv must contain two finite values")
            object.__setattr__(self, "center_uv", tuple(float(value) for value in self.center_uv))
        if self.width_px is not None and (not np.isfinite(self.width_px) or self.width_px <= 0.0):
            raise ValueError("width_px must be finite and positive")
        if self.target_mask_margin_px < 0.0 or not np.isfinite(self.target_mask_margin_px):
            raise ValueError("target_mask_margin_px must be finite and non-negative")
        reasons = tuple(dict.fromkeys(reason for reason in self.rejection_reasons if reason.strip()))
        if self.feasibility is CandidateFeasibility.EXECUTABLE and reasons:
            raise ValueError("executable candidates cannot contain rejection reasons")
        if self.feasibility is CandidateFeasibility.REJECTED and not reasons:
            raise ValueError("rejected candidates require rejection reasons")
        object.__setattr__(self, "rejection_reasons", reasons)
        object.__setattr__(self, "score_factors", dict(self.score_factors))

    @property
    def executable(self) -> bool:
        return self.feasibility is CandidateFeasibility.EXECUTABLE

    def public_metadata(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "center_uv": None if self.center_uv is None else list(self.center_uv),
            "angle_rad": self.grasp_angle,
            "angle_deg": float(np.degrees(self.grasp_angle)),
            "width_px": self.width_px,
            "width_m": self.gripper_width,
            "quality": self.quality_score,
            "ranking_score": self.ranking_score,
            "grasp_center_xyz": self.grasp_point_xyz.tolist(),
            "approach_direction": self.approach_vector.tolist(),
            "closing_direction": self.closing_vector.tolist(),
            "feasibility": self.feasibility.value,
            "rejection_reasons": list(self.rejection_reasons),
            "source_frame_id": self.source_frame_id,
            "target_instance_id": self.target_instance_id,
            "checks": {
                "target_mask_margin_px": self.target_mask_margin_px,
                "valid_depth_ratio": self.valid_depth_ratio,
                "width_compatibility": self.width_compatibility,
                "geometry_confidence": self.geometry_confidence,
                "workspace_reachability": self.reachability.value,
                "collision_feasibility": self.collision_feasibility.value,
            },
            "score_factors": dict(self.score_factors),
        }


@dataclass(frozen=True, slots=True)
class GraspPlan:
    """Best executable map-derived grasp with its complete Top-K audit trail."""

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
    candidates: tuple[GraspCandidate, ...] = ()
    best_candidate_id: str | None = None
    spatial_observation_id: str | None = None
    planning_time_s: float = 0.0
    mode: PlanningMode = PlanningMode.RESEARCH
    model_metadata: dict[str, Any] | None = None
    condition_report: ConditionReport | None = None
    perception_uncertainty: PerceptionUncertainty | None = None
    spatial_uncertainty: SpatialUncertainty | None = None
    grasp_uncertainty: GraspUncertainty | None = None

    def __post_init__(self) -> None:
        if not self.target_id.strip() or not self.snapshot_id.strip():
            raise ValueError("target_id and snapshot_id must not be empty")
        if self.source_frame_id < 0:
            raise ValueError("source_frame_id must be non-negative")
        if self.planning_state is not PlanningState.GRASP_READY:
            raise ValueError("serialized GraspPlan must be GRASP_READY")
        if not self.source.strip() or not self.coordinate_frame.strip():
            raise ValueError("source and coordinate_frame must not be empty")
        if self.candidate_count < 1:
            raise ValueError("candidate_count must be positive")
        if self.candidates and self.candidate_count != len(self.candidates):
            raise ValueError("candidate_count must match candidates")
        if self.candidates and self.best_candidate_id not in {candidate.candidate_id for candidate in self.candidates}:
            raise ValueError("best_candidate_id must name a candidate")
        if not np.isfinite(self.planning_time_s) or self.planning_time_s < 0.0:
            raise ValueError("planning_time_s must be finite and non-negative")
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
            if name in {"approach_vector", "closing_vector"} and not np.isclose(np.linalg.norm(value), 1.0, atol=1e-6):
                raise ValueError(f"{name} must be a unit vector")
            if name == "object_extents_xyz" and np.any(value <= 0.0):
                raise ValueError("object_extents_xyz must be positive")
            immutable = np.ascontiguousarray(value.copy())
            immutable.setflags(write=False)
            object.__setattr__(self, name, immutable)
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(self, "uncertainty", tuple(dict.fromkeys(self.uncertainty)))
        object.__setattr__(self, "model_metadata", dict(self.model_metadata or {}))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": GRASP_PLAN_SCHEMA_VERSION,
            "target_id": self.target_id,
            "snapshot_id": self.snapshot_id,
            "source_frame_id": self.source_frame_id,
            "spatial_observation_id": self.spatial_observation_id,
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
            "best_candidate_id": self.best_candidate_id,
            "candidates": [candidate.public_metadata() for candidate in self.candidates],
            "planning_time_s": self.planning_time_s,
            "mode": self.mode.value,
            "model_metadata": dict(self.model_metadata or {}),
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
            "grasp_uncertainty": (
                None
                if self.grasp_uncertainty is None
                else self.grasp_uncertainty.public_metadata()
            ),
            "execution_scope": "ROBOT_INDEPENDENT_CAMERA_FRAME",
        }


@dataclass(frozen=True, slots=True)
class GraspMaps:
    quality: NDArray[np.float32]
    angle: NDArray[np.float32]
    width_px: NDArray[np.float32]
    crop_xyxy: tuple[int, int, int, int]
    model_input_size: tuple[int, int]
    inference_time_s: float
    model_load_time_s: float
    model_was_ready: bool
    compute_device: str
    model_location: str

    def __post_init__(self) -> None:
        shape: tuple[int, int] | None = None
        for name in ("quality", "angle", "width_px"):
            value = np.asarray(getattr(self, name), dtype=np.float32)
            if value.ndim != 2 or value.size == 0 or not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must be a finite non-empty 2D map")
            if shape is None:
                shape = value.shape
            elif value.shape != shape:
                raise ValueError("grasp maps must share one shape")
            immutable = np.ascontiguousarray(value.copy())
            immutable.setflags(write=False)
            object.__setattr__(self, name, immutable)
        for name in ("inference_time_s", "model_load_time_s"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")

    def public_metadata(self) -> dict[str, Any]:
        return {
            "shape": {"width": int(self.quality.shape[1]), "height": int(self.quality.shape[0])},
            "crop_xyxy": list(self.crop_xyxy),
            "model_input_size": list(self.model_input_size),
            "inference_time_s": self.inference_time_s,
            "model_load_time_s": self.model_load_time_s,
            "model_was_ready": self.model_was_ready,
            "compute_device": self.compute_device,
            "model_location": self.model_location,
            "quality_range": [float(np.min(self.quality)), float(np.max(self.quality))],
            "angle_range_rad": [float(np.min(self.angle)), float(np.max(self.angle))],
            "width_range_px": [float(np.min(self.width_px)), float(np.max(self.width_px))],
        }


@dataclass(frozen=True, slots=True)
class GraspPlanningOutcome:
    candidates: tuple[GraspCandidate, ...]
    maps: GraspMaps
    object_extents_xyz: NDArray[np.float64]
    plan: GraspPlan | None
    rejection_reason: str | None
    planning_time_s: float
    condition_report: ConditionReport | None = None
    perception_uncertainty: PerceptionUncertainty | None = None
    spatial_uncertainty: SpatialUncertainty | None = None
    grasp_uncertainty: GraspUncertainty | None = None

    def __post_init__(self) -> None:
        extents = np.asarray(self.object_extents_xyz, dtype=np.float64)
        if extents.shape != (3,) or not np.all(np.isfinite(extents)) or np.any(extents <= 0.0):
            raise ValueError("object_extents_xyz must be a finite positive 3-vector")
        immutable = np.ascontiguousarray(extents.copy())
        immutable.setflags(write=False)
        object.__setattr__(self, "object_extents_xyz", immutable)

    @property
    def ready(self) -> bool:
        return self.plan is not None

    def visualization_request(self) -> dict[str, Any]:
        condition_warnings = (
            [] if self.grasp_uncertainty is None else list(self.grasp_uncertainty.reasons)
        )
        return {
            "schema_version": "gongshu.grasp-visualization-request/v1",
            "planning_status": "GRASP_READY" if self.plan is not None else "PLANNING_REJECTED",
            "rejection_reason": self.rejection_reason,
            "condition_warnings": condition_warnings,
            "source_frame_id": (
                self.plan.source_frame_id
                if self.plan is not None
                else (self.candidates[0].source_frame_id if self.candidates else None)
            ),
            "target_instance_id": (
                self.plan.target_id
                if self.plan is not None
                else (self.candidates[0].target_instance_id if self.candidates else None)
            ),
            "candidate_count": len(self.candidates),
            "best_candidate_id": None if self.plan is None else self.plan.best_candidate_id,
            "object_extents_xyz": self.object_extents_xyz.tolist(),
            "candidates": [candidate.public_metadata() for candidate in self.candidates],
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
            "grasp_uncertainty": (
                None
                if self.grasp_uncertainty is None
                else self.grasp_uncertainty.public_metadata()
            ),
        }
