"""Platform-owned Intelligence Layer orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
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
from .switcher import (
    ActiveAlgorithm,
    ActiveAlgorithmSelector,
    AlgorithmLoader,
    DecisionEngine,
)
from .visualization import VisualizationDataProvider, XiezhiDashboardState


class IntelligenceService:
    """Select an algorithm provider while keeping Gongshu independently runnable."""

    def __init__(
        self,
        *,
        xiezhi_enabled: bool,
        algorithm_id: str = "xiezhi_decision_v0_1",
        registry: AlgorithmRegistry | None = None,
        active_algorithm_state_path: str | Path | None = None,
    ) -> None:
        self._xiezhi_enabled = bool(xiezhi_enabled)
        self._registry = registry or default_algorithm_registry(
            include_xiezhi=xiezhi_enabled,
            include_mock_external=True,
        )
        self._visualization = VisualizationDataProvider(self._registry)
        default_algorithm_id = algorithm_id if xiezhi_enabled else "baseline_topk"
        self._selector = ActiveAlgorithmSelector(
            self._registry,
            default_algorithm_id,
            state_path=active_algorithm_state_path,
        )
        self._loader = AlgorithmLoader(self._registry)
        self._decision_engine = DecisionEngine(self._selector, self._loader)
        self._lock = threading.RLock()
        self._revision = 0
        self._decision: AlgorithmDecision | None = None
        self._decision_history: list[AlgorithmDecision] = []
        self._observation_id: str | None = None
        self._provider_status = "READY"
        self._provider_id = self._selector.get_active().provider_id
        self._fallback_reason: str | None = None

    def reset(self) -> dict[str, Any]:
        with self._lock:
            self._revision += 1
            self._decision = None
            self._decision_history.clear()
            self._observation_id = None
            self._provider_status = "READY"
            self._provider_id = self._selector.get_active().provider_id
            self._fallback_reason = None
            return self.snapshot()

    def decide(self, outcome: GraspPlanningOutcome) -> AlgorithmDecision:
        observation = self._observation(outcome)
        with self._lock:
            if self._decision is not None and self._observation_id == observation.observation_id:
                return self._decision
        active = self._selector.get_active()
        fallback_reason = None
        if active.provider_id == "xiezhi":
            try:
                decision = self._decision_engine.decide(observation)
                provider_status = "READY"
                provider_id = active.provider_id
            except (ImportError, RuntimeError, TypeError, ValueError) as error:
                fallback_reason = f"{type(error).__name__}: {error}"
                decision = as_fallback(
                    self._loader.decide("baseline_topk", observation),
                    fallback_reason,
                )
                provider_status = "DEGRADED"
                provider_id = "gongshu"
        else:
            decision = self._decision_engine.decide(observation)
            provider_status = "READY"
            provider_id = active.provider_id
        with self._lock:
            self._revision += 1
            self._decision = decision
            self._decision_history.append(decision)
            self._decision_history = self._decision_history[-20:]
            self._observation_id = observation.observation_id
            self._provider_status = provider_status
            self._provider_id = provider_id
            self._fallback_reason = fallback_reason
            return decision

    def ensure_decision(self, outcome: GraspPlanningOutcome) -> AlgorithmDecision:
        return self.decide(outcome)

    def select_algorithm(self, provider_id: str, algorithm_id: str) -> dict[str, Any]:
        provider = str(provider_id).strip().lower()
        algorithm = str(algorithm_id).strip().lower()
        try:
            loaded = self._loader.load(algorithm)
        except ValueError as error:
            raise ValueError(
                f"algorithm provider is not available: {provider}/{algorithm}"
            ) from error
        if loaded.provider_id != provider:
            raise ValueError(f"algorithm provider is not available: {provider}/{algorithm}")
        self.set_active_algorithm(algorithm)
        return self.snapshot()

    def set_active_algorithm(self, algorithm_id: str) -> ActiveAlgorithm:
        """Switch the Decision Engine by algorithm ID without Runtime changes."""

        active = self._decision_engine.set_active_algorithm(algorithm_id)
        with self._lock:
            self._provider_id = active.provider_id
            self._provider_status = "READY"
            self._fallback_reason = None
            self._decision = None
            self._observation_id = None
            self._revision += 1
        return active

    def active_algorithm(self) -> ActiveAlgorithm:
        return self._decision_engine.active_algorithm()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = self._selector.get_active()
            decision = None if self._decision is None else self._decision.public_metadata()
            return {
                "schema_version": INTELLIGENCE_STATE_SCHEMA_VERSION,
                "status": self._provider_status,
                "configured_provider": active.provider_id,
                "selected_provider": active.provider_id,
                "selected_algorithm": active.algorithm_id,
                "active_algorithm": active.public_metadata(),
                "active_provider": self._provider_id,
                "algorithm": (
                    active.algorithm_id
                    if self._provider_id == active.provider_id
                    else "baseline_topk"
                ),
                "decision_available": decision is not None,
                "last_decision": decision,
                "decision_history": [
                    item.public_metadata() for item in reversed(self._decision_history)
                ],
                "fallback_reason": self._fallback_reason,
                "available_algorithms": list(self._registry.entries()),
                "revision": self._revision,
            }

    def dashboard_state(self) -> XiezhiDashboardState | None:
        """Return the read-only XiezhiDashboardState v1 projection, when available."""

        with self._lock:
            decision = self._decision
        if decision is None:
            return None
        try:
            return self._visualization.build(
                decision,
                active_algorithm=self._selector.get_active().public_metadata(),
            )
        except ValueError:
            return None

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
