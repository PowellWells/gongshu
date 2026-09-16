"""Gongshu-owned contracts for algorithm-provider decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
from numpy.typing import NDArray


INTELLIGENCE_DECISION_SCHEMA_VERSION = "gongshu.intelligence-decision/v1"
INTELLIGENCE_STATE_SCHEMA_VERSION = "gongshu.intelligence-state/v1"


class DecisionStatus(str, Enum):
    ACTION_AVAILABLE = "ACTION_AVAILABLE"
    ABSTAINED = "ABSTAINED"


class DecisionAction(str, Enum):
    EXECUTE_GRASP = "EXECUTE_GRASP"
    REOBSERVE = "REOBSERVE"
    CHANGE_VIEWPOINT = "CHANGE_VIEWPOINT"
    RECOVER = "RECOVER"
    ABORT = "ABORT"
    NO_ACTION = "NO_ACTION"


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """Decision-safe grasp evidence without simulator or robot objects."""

    candidate_id: str
    target_id: str
    grasp_point_xyz: NDArray[np.float64]
    approach_vector: NDArray[np.float64]
    closing_vector: NDArray[np.float64]
    gripper_width_m: float
    score: float
    executable: bool
    score_factors: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.target_id.strip():
            raise ValueError("candidate and target identifiers must not be empty")
        for name in ("grasp_point_xyz", "approach_vector", "closing_vector"):
            value = np.asarray(getattr(self, name), dtype=np.float64)
            if value.shape != (3,) or not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must be a finite 3-vector")
            immutable = np.ascontiguousarray(value.copy())
            immutable.setflags(write=False)
            object.__setattr__(self, name, immutable)
        if not isfinite(self.gripper_width_m) or self.gripper_width_m <= 0:
            raise ValueError("gripper_width_m must be finite and positive")
        if not isfinite(self.score) or not 0 <= self.score <= 1:
            raise ValueError("score must be in [0, 1]")
        object.__setattr__(self, "score_factors", MappingProxyType(dict(self.score_factors)))


@dataclass(frozen=True, slots=True)
class AlgorithmObservation:
    """Stable state representation presented to every algorithm provider."""

    observation_id: str
    episode_id: str
    revision: int
    timestamp_s: float
    target_id: str
    candidates: tuple[CandidateEvidence, ...]
    best_candidate_id: str | None
    evidence_confidence: float | None
    reliability: str
    uncertainty_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("observation_id", "episode_id", "target_id", "reliability"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if self.revision < 0 or self.timestamp_s < 0 or not isfinite(self.timestamp_s):
            raise ValueError("revision and timestamp must be non-negative")
        candidates = tuple(self.candidates)
        candidate_ids = {candidate.candidate_id for candidate in candidates}
        if len(candidate_ids) != len(candidates):
            raise ValueError("candidate IDs must be unique")
        if self.best_candidate_id is not None and self.best_candidate_id not in candidate_ids:
            raise ValueError("best_candidate_id must name a candidate")
        if self.evidence_confidence is not None and (
            not isfinite(self.evidence_confidence) or not 0 <= self.evidence_confidence <= 1
        ):
            raise ValueError("evidence_confidence must be None or in [0, 1]")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "uncertainty_reasons", tuple(self.uncertainty_reasons))


@dataclass(frozen=True, slots=True)
class AlgorithmDecision:
    """Provider-neutral result consumed only by Gongshu Runtime."""

    decision_id: str
    observation_id: str
    provider_id: str
    algorithm_id: str
    status: DecisionStatus
    selected_action: DecisionAction
    selected_candidate_id: str | None
    confidence: float | None
    risk_estimation: float | None
    reason: str
    used_fallback: bool = False
    fallback_reason: str | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("decision_id", "observation_id", "provider_id", "algorithm_id", "reason"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        for name in ("confidence", "risk_estimation"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{name} must be None or in [0, 1]")
        if self.selected_action is DecisionAction.EXECUTE_GRASP and not self.selected_candidate_id:
            raise ValueError("EXECUTE_GRASP requires selected_candidate_id")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def authorizes_execution(self) -> bool:
        return (
            self.status is DecisionStatus.ACTION_AVAILABLE
            and self.selected_action is DecisionAction.EXECUTE_GRASP
            and self.selected_candidate_id is not None
        )

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": INTELLIGENCE_DECISION_SCHEMA_VERSION,
            "decision_id": self.decision_id,
            "observation_id": self.observation_id,
            "provider": self.provider_id,
            "algorithm": self.algorithm_id,
            "status": self.status.value,
            "selected_action": self.selected_action.value,
            "selected_candidate_id": self.selected_candidate_id,
            "confidence": self.confidence,
            "confidence_type": "HEURISTIC_UNCALIBRATED",
            "risk_estimation": self.risk_estimation,
            "risk_type": "HEURISTIC_UNCALIBRATED",
            "reason": self.reason,
            "used_fallback": self.used_fallback,
            "fallback_reason": self.fallback_reason,
            "diagnostics": dict(self.diagnostics),
        }


__all__ = [
    "AlgorithmDecision",
    "AlgorithmObservation",
    "CandidateEvidence",
    "DecisionAction",
    "DecisionStatus",
    "INTELLIGENCE_DECISION_SCHEMA_VERSION",
    "INTELLIGENCE_STATE_SCHEMA_VERSION",
]
