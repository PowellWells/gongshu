"""Gongshu baseline and optional Xiezhi algorithm providers."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol
from uuid import uuid4

from vision2grasp.extensions.xiezhi.algorithms import (
    XIEZHI_DECISION_V0_1_ID,
    XIEZHI_DECISION_V0_1_METADATA,
    XiezhiDecisionV01,
)

from .contracts import (
    AlgorithmDecision,
    AlgorithmObservation,
    CandidateEvidence,
    DecisionAction,
    DecisionStatus,
)


class AlgorithmProvider(Protocol):
    provider_id: str
    algorithm_id: str

    def decide(self, observation: AlgorithmObservation) -> AlgorithmDecision: ...


def _decision_id() -> str:
    return f"decision-{uuid4().hex[:16]}"


def _selected_evidence(
    observation: AlgorithmObservation, candidate_id: str | None
) -> CandidateEvidence | None:
    return next(
        (candidate for candidate in observation.candidates if candidate.candidate_id == candidate_id),
        None,
    )


class BaselineDecisionProvider:
    """Gongshu-owned deterministic fallback over the planner's ranked candidates."""

    provider_id = "gongshu"
    algorithm_id = "baseline_topk"

    def decide(self, observation: AlgorithmObservation) -> AlgorithmDecision:
        selected = _selected_evidence(observation, observation.best_candidate_id)
        if selected is None or not selected.executable:
            return AlgorithmDecision(
                decision_id=_decision_id(),
                observation_id=observation.observation_id,
                provider_id=self.provider_id,
                algorithm_id=self.algorithm_id,
                status=DecisionStatus.ABSTAINED,
                selected_action=DecisionAction.NO_ACTION,
                selected_candidate_id=None,
                confidence=None,
                risk_estimation=None,
                reason="no_executable_grasp_candidate",
                uncertainty=observation.uncertainty_reasons,
                diagnostics={"candidate_count": len(observation.candidates)},
            )
        confidence = float(selected.score)
        return AlgorithmDecision(
            decision_id=_decision_id(),
            observation_id=observation.observation_id,
            provider_id=self.provider_id,
            algorithm_id=self.algorithm_id,
            status=DecisionStatus.ACTION_AVAILABLE,
            selected_action=DecisionAction.EXECUTE_GRASP,
            selected_candidate_id=selected.candidate_id,
            confidence=confidence,
            risk_estimation=float(1.0 - confidence),
            reason="best_executable_ranked_candidate",
            uncertainty=observation.uncertainty_reasons,
            diagnostics={"candidate_count": len(observation.candidates)},
        )


class XiezhiDecisionProvider:
    """Expose formal Xiezhi Decision v0.1 through Gongshu's provider boundary."""

    provider_id = "xiezhi"
    algorithm_id = XIEZHI_DECISION_V0_1_ID
    metadata = XIEZHI_DECISION_V0_1_METADATA

    def __init__(self) -> None:
        self._algorithm = XiezhiDecisionV01()

    def decide(self, observation: AlgorithmObservation) -> AlgorithmDecision:
        return self._algorithm.decide(observation)


def as_fallback(decision: AlgorithmDecision, reason: str) -> AlgorithmDecision:
    return replace(decision, used_fallback=True, fallback_reason=reason)


__all__ = [
    "AlgorithmProvider",
    "BaselineDecisionProvider",
    "XiezhiDecisionProvider",
    "as_fallback",
]
