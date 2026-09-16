"""Platform-owned Intelligence Layer orchestration."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import Any

from vision2grasp.grasp_planning import GraspPlanningOutcome

from .contracts import (
    AlgorithmDecision,
    AlgorithmObservation,
    CandidateEvidence,
    INTELLIGENCE_STATE_SCHEMA_VERSION,
)
from .providers import as_fallback
from .registry import AlgorithmRegistry, default_algorithm_registry


class IntelligenceService:
    """Select an algorithm provider while keeping Gongshu independently runnable."""

    def __init__(
        self,
        *,
        xiezhi_enabled: bool,
        algorithm_id: str = "rule_based",
        registry: AlgorithmRegistry | None = None,
    ) -> None:
        self._xiezhi_enabled = bool(xiezhi_enabled)
        self._algorithm_id = algorithm_id
        self._registry = registry or default_algorithm_registry(include_xiezhi=xiezhi_enabled)
        self._lock = threading.RLock()
        self._revision = 0
        self._decision: AlgorithmDecision | None = None
        self._observation_id: str | None = None
        self._provider_status = "READY"
        self._provider_id = "xiezhi" if xiezhi_enabled else "gongshu"
        self._fallback_reason: str | None = None

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._revision += 1
            self._decision = None
            self._observation_id = None
            self._provider_status = "READY"
            self._provider_id = "xiezhi" if self._xiezhi_enabled else "gongshu"
            self._fallback_reason = None
            return self.snapshot()

    def decide(self, outcome: GraspPlanningOutcome) -> AlgorithmDecision:
        observation = self._observation(outcome)
        with self._lock:
            if self._decision is not None and self._observation_id == observation.observation_id:
                return self._decision
        fallback_reason = None
        if self._xiezhi_enabled:
            try:
                decision = self._registry.create("xiezhi", self._algorithm_id).decide(observation)
                provider_status = "READY"
                provider_id = "xiezhi"
            except (ImportError, RuntimeError, TypeError, ValueError) as error:
                fallback_reason = f"{type(error).__name__}: {error}"
                baseline = self._registry.create("gongshu", "baseline_topk")
                decision = as_fallback(baseline.decide(observation), fallback_reason)
                provider_status = "DEGRADED"
                provider_id = "gongshu"
        else:
            decision = self._registry.create("gongshu", "baseline_topk").decide(observation)
            provider_status = "READY"
            provider_id = "gongshu"
        with self._lock:
            self._revision += 1
            self._decision = decision
            self._observation_id = observation.observation_id
            self._provider_status = provider_status
            self._provider_id = provider_id
            self._fallback_reason = fallback_reason
            return decision

    def ensure_decision(self, outcome: GraspPlanningOutcome) -> AlgorithmDecision:
        return self.decide(outcome)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            decision = None if self._decision is None else self._decision.public_metadata()
            return {
                "schema_version": INTELLIGENCE_STATE_SCHEMA_VERSION,
                "status": self._provider_status,
                "configured_provider": "xiezhi" if self._xiezhi_enabled else "gongshu",
                "active_provider": self._provider_id,
                "algorithm": (
                    self._algorithm_id if self._provider_id == "xiezhi" else "baseline_topk"
                ),
                "decision_available": decision is not None,
                "last_decision": decision,
                "fallback_reason": self._fallback_reason,
                "available_algorithms": list(self._registry.entries()),
                "revision": self._revision,
            }

    def _observation(self, outcome: GraspPlanningOutcome) -> AlgorithmObservation:
        plan = outcome.plan
        first = outcome.candidates[0] if outcome.candidates else None
        target_id = plan.target_id if plan is not None else (
            first.target_instance_id if first is not None else "unknown-target"
        )
        source_frame_id = plan.source_frame_id if plan is not None else (
            first.source_frame_id if first is not None else 0
        )
        snapshot_id = plan.snapshot_id if plan is not None else f"rejected-frame-{source_frame_id}"
        observation_id = f"{snapshot_id}:{source_frame_id}:{len(outcome.candidates)}:{outcome.planning_time_s:.9f}"
        uncertainty = outcome.grasp_uncertainty or outcome.spatial_uncertainty
        evidence_confidence = (
            plan.confidence.value
            if plan is not None
            else (None if uncertainty is None else uncertainty.confidence)
        )
        reliability = "UNKNOWN" if uncertainty is None else uncertainty.level.value
        reasons = () if uncertainty is None else uncertainty.reasons
        candidates = tuple(CandidateEvidence(
            candidate_id=candidate.candidate_id,
            target_id=candidate.target_instance_id or target_id,
            grasp_point_xyz=candidate.grasp_point_xyz,
            approach_vector=candidate.approach_vector,
            closing_vector=candidate.closing_vector,
            gripper_width_m=candidate.gripper_width,
            score=candidate.ranking_score,
            executable=candidate.executable,
            score_factors=candidate.score_factors,
        ) for candidate in outcome.candidates)
        return AlgorithmObservation(
            observation_id=observation_id,
            episode_id=snapshot_id,
            revision=self._revision,
            timestamp_s=datetime.now().timestamp(),
            target_id=target_id,
            candidates=candidates,
            best_candidate_id=None if plan is None else plan.best_candidate_id,
            evidence_confidence=evidence_confidence,
            reliability=reliability,
            uncertainty_reasons=reasons,
        )


__all__ = ["IntelligenceService"]
