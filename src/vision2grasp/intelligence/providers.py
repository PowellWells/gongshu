"""Gongshu baseline and optional Xiezhi algorithm providers."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol
from uuid import uuid4

import numpy as np

from vision2grasp.contracts import GraspCandidate as LegacyGraspCandidate
from vision2grasp.extensions.xiezhi.backend import MayflowerXiezhiDecisionBackend
from vision2grasp.extensions.xiezhi.contracts import GongshuObservation

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
            diagnostics={"candidate_count": len(observation.candidates)},
        )


def _legacy_candidate(candidate: CandidateEvidence) -> LegacyGraspCandidate:
    approach = np.asarray(candidate.approach_vector, dtype=np.float64).copy()
    approach /= np.linalg.norm(approach)
    closing = np.asarray(candidate.closing_vector, dtype=np.float64).copy()
    closing = closing - float(np.dot(closing, approach)) * approach
    if np.linalg.norm(closing) < 1e-8:
        reference = np.array((1.0, 0.0, 0.0), dtype=np.float64)
        if abs(float(np.dot(reference, approach))) > 0.9:
            reference = np.array((0.0, 1.0, 0.0), dtype=np.float64)
        closing = reference - float(np.dot(reference, approach)) * approach
    closing /= np.linalg.norm(closing)
    lateral = np.cross(approach, closing)
    lateral /= np.linalg.norm(lateral)
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = np.column_stack((closing, lateral, approach))
    transform[:3, 3] = candidate.grasp_point_xyz
    return LegacyGraspCandidate(
        candidate_id=candidate.candidate_id,
        world_from_grasp=transform,
        gripper_width_m=candidate.gripper_width_m,
        score=candidate.score,
        reachable=candidate.executable,
        score_terms=candidate.score_factors,
    )


class XiezhiDecisionProvider:
    """Adapter that lets Xiezhi decide without owning Gongshu execution."""

    provider_id = "xiezhi"

    def __init__(self, algorithm_id: str = "rule_based") -> None:
        self.algorithm_id = algorithm_id
        self._backend = MayflowerXiezhiDecisionBackend(algorithm_id)

    def decide(self, observation: AlgorithmObservation) -> AlgorithmDecision:
        confidence = observation.evidence_confidence
        position_std = None if confidence is None else 0.004 + (1.0 - confidence) * 0.032
        rotation_std = None if confidence is None else 0.03 + (1.0 - confidence) * 0.18
        result = self._backend.decide(GongshuObservation(
            episode_id=observation.episode_id,
            observation_id=observation.observation_id,
            revision=observation.revision,
            timestamp_s=observation.timestamp_s,
            target_object_id=observation.target_id,
            candidates=tuple(
                _legacy_candidate(candidate)
                for candidate in observation.candidates
                if candidate.executable
            ),
            position_std_m=position_std,
            rotation_std_rad=rotation_std,
            quality=confidence,
            occlusion=0.0,
            robot_state={
                "coordinate_frame": "OPENCV_CAMERA_X_RIGHT_Y_DOWN_Z_FORWARD",
                "reliability": observation.reliability,
            },
        ))
        action_map = {
            "ExecuteGrasp": DecisionAction.EXECUTE_GRASP,
            "Reobserve": DecisionAction.REOBSERVE,
            "ChangeViewpoint": DecisionAction.CHANGE_VIEWPOINT,
            "Recover": DecisionAction.RECOVER,
            "Abort": DecisionAction.ABORT,
        }
        action = action_map.get(result.action_name, DecisionAction.NO_ACTION)
        selected = _selected_evidence(observation, result.candidate_id)
        selected_confidence = (
            observation.evidence_confidence
            if selected is None
            else float(selected.score)
        )
        reason = str(result.diagnostics.get("reason") or result.stop_reason or "provider_decision")
        return AlgorithmDecision(
            decision_id=_decision_id(),
            observation_id=observation.observation_id,
            provider_id=self.provider_id,
            algorithm_id=self.algorithm_id,
            status=(
                DecisionStatus.ACTION_AVAILABLE
                if action is not DecisionAction.NO_ACTION
                else DecisionStatus.ABSTAINED
            ),
            selected_action=action,
            selected_candidate_id=result.candidate_id,
            confidence=selected_confidence,
            risk_estimation=(
                None if selected_confidence is None else float(1.0 - selected_confidence)
            ),
            reason=reason,
            diagnostics={
                **dict(result.diagnostics),
                "position_std_proxy_m": position_std,
                "rotation_std_proxy_rad": rotation_std,
                "uncertainty_reasons": list(observation.uncertainty_reasons),
                "executable_candidate_count": sum(
                    1 for candidate in observation.candidates if candidate.executable
                ),
            },
        )


def as_fallback(decision: AlgorithmDecision, reason: str) -> AlgorithmDecision:
    return replace(decision, used_fallback=True, fallback_reason=reason)


__all__ = [
    "AlgorithmProvider",
    "BaselineDecisionProvider",
    "XiezhiDecisionProvider",
    "as_fallback",
]
