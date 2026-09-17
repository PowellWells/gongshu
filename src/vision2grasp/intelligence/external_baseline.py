"""Adapter boundary for external reference algorithms.

No external implementation is bundled here. The adapter only translates Gongshu's
state representation to a neutral input and translates a result to AlgorithmDecision v1.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any, Protocol
from uuid import uuid4

from .blueprint import AlgorithmMetadata, AlgorithmStatus, AlgorithmType
from .contracts import (
    INTELLIGENCE_DECISION_SCHEMA_VERSION,
    AlgorithmDecision,
    AlgorithmObservation,
    DecisionAction,
    DecisionStatus,
)


EXTERNAL_BASELINE_PROVIDER_ID = "external_baseline"
MOCK_EXTERNAL_BASELINE_ID = "mock_external_baseline_v0_1"


@dataclass(frozen=True, slots=True)
class ExternalCandidateInput:
    candidate_id: str
    target_id: str
    score: float
    executable: bool
    grasp_point_xyz: tuple[float, float, float]
    approach_vector: tuple[float, float, float]
    closing_vector: tuple[float, float, float]
    gripper_width_m: float
    score_factors: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.target_id.strip():
            raise ValueError("external candidate identifiers must not be empty")
        if not isfinite(self.score) or not 0 <= self.score <= 1:
            raise ValueError("external candidate score must be in [0, 1]")
        object.__setattr__(self, "score_factors", MappingProxyType(dict(self.score_factors)))


@dataclass(frozen=True, slots=True)
class ExternalBaselineInput:
    observation_id: str
    target_id: str
    candidates: tuple[ExternalCandidateInput, ...]
    evidence_confidence: float | None
    reliability: str
    uncertainty: tuple[str, ...] = ()
    robot_state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.observation_id.strip() or not self.target_id.strip():
            raise ValueError("external baseline input identifiers must not be empty")
        candidates = tuple(self.candidates)
        if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise ValueError("external baseline candidate IDs must be unique")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "uncertainty", tuple(self.uncertainty))
        object.__setattr__(self, "robot_state", MappingProxyType(dict(self.robot_state)))


@dataclass(frozen=True, slots=True)
class ExternalBaselineOutput:
    action: DecisionAction
    selected_candidate_id: str | None
    confidence: float | None
    risk_estimation: float | None
    reason: str
    uncertainty: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            action = DecisionAction(self.action)
        except ValueError as error:
            raise ValueError("external baseline returned an unsupported action") from error
        for name in ("confidence", "risk_estimation"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{name} must be None or in [0, 1]")
        if not self.reason.strip():
            raise ValueError("external baseline reason must not be empty")
        if action is DecisionAction.EXECUTE_GRASP and not self.selected_candidate_id:
            raise ValueError("external EXECUTE_GRASP requires selected_candidate_id")
        if action is not DecisionAction.EXECUTE_GRASP and self.selected_candidate_id:
            raise ValueError("only external EXECUTE_GRASP may select a candidate")
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "uncertainty", tuple(self.uncertainty))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


class ExternalAlgorithm(Protocol):
    def decide(self, input_data: ExternalBaselineInput) -> ExternalBaselineOutput: ...


class ExternalBaselineAdapter:
    """Bind one external algorithm identity to AlgorithmDecision v1."""

    def __init__(self, metadata: AlgorithmMetadata, algorithm: ExternalAlgorithm) -> None:
        if metadata.type is not AlgorithmType.EXTERNAL_BASELINE:
            raise ValueError("external adapter requires External Baseline metadata")
        if not callable(getattr(algorithm, "decide", None)):
            raise TypeError("external algorithm must implement decide")
        self.metadata = metadata
        self.provider_id = metadata.provider_id
        self.algorithm_id = metadata.algorithm_id
        self._algorithm = algorithm

    @staticmethod
    def _convert_input(observation: AlgorithmObservation) -> ExternalBaselineInput:
        return ExternalBaselineInput(
            observation_id=observation.observation_id,
            target_id=observation.target_id,
            candidates=tuple(
                ExternalCandidateInput(
                    candidate_id=candidate.candidate_id,
                    target_id=candidate.target_id,
                    score=float(candidate.score),
                    executable=candidate.executable,
                    grasp_point_xyz=tuple(float(value) for value in candidate.grasp_point_xyz),
                    approach_vector=tuple(float(value) for value in candidate.approach_vector),
                    closing_vector=tuple(float(value) for value in candidate.closing_vector),
                    gripper_width_m=float(candidate.gripper_width_m),
                    score_factors=candidate.score_factors,
                )
                for candidate in observation.candidates
            ),
            evidence_confidence=observation.evidence_confidence,
            reliability=observation.reliability,
            uncertainty=observation.uncertainty_reasons,
            robot_state=observation.robot_state,
        )

    def decide(self, observation: AlgorithmObservation) -> AlgorithmDecision:
        input_data = self._convert_input(observation)
        output = self._algorithm.decide(input_data)
        if not isinstance(output, ExternalBaselineOutput):
            raise TypeError("external algorithm must return ExternalBaselineOutput")
        selected = next(
            (
                candidate
                for candidate in input_data.candidates
                if candidate.candidate_id == output.selected_candidate_id
            ),
            None,
        )
        if output.action is DecisionAction.EXECUTE_GRASP and (
            selected is None or not selected.executable
        ):
            raise ValueError("external baseline selected an unavailable candidate")
        return AlgorithmDecision(
            decision_id=f"decision-{uuid4().hex[:16]}",
            observation_id=observation.observation_id,
            provider_id=self.provider_id,
            algorithm_id=self.algorithm_id,
            status=(
                DecisionStatus.ABSTAINED
                if output.action is DecisionAction.NO_ACTION
                else DecisionStatus.ACTION_AVAILABLE
            ),
            selected_action=output.action,
            selected_candidate_id=output.selected_candidate_id,
            confidence=output.confidence,
            risk_estimation=output.risk_estimation,
            reason=output.reason,
            uncertainty=tuple(
                dict.fromkeys((*observation.uncertainty_reasons, *output.uncertainty))
            ),
            diagnostics={
                **dict(output.diagnostics),
                "adapter": "ExternalBaselineAdapter",
                "algorithm_metadata": self.metadata.public_metadata(),
            },
        )


class MockSelectionStrategy(str, Enum):
    HIGHEST_SCORE = "highest_score"
    FIRST_EXECUTABLE = "first_executable"


class MockExternalBaseline:
    """Minimal deterministic test algorithm; not an external project integration."""

    def __init__(
        self,
        strategy: MockSelectionStrategy = MockSelectionStrategy.HIGHEST_SCORE,
    ) -> None:
        self.strategy = MockSelectionStrategy(strategy)

    def decide(self, input_data: ExternalBaselineInput) -> ExternalBaselineOutput:
        candidates = [candidate for candidate in input_data.candidates if candidate.executable]
        if not candidates:
            return ExternalBaselineOutput(
                action=DecisionAction.REOBSERVE,
                selected_candidate_id=None,
                confidence=input_data.evidence_confidence,
                risk_estimation=None,
                reason="mock_no_executable_candidate",
                uncertainty=("NO_EXECUTABLE_CANDIDATE",),
                diagnostics={"strategy": self.strategy.value},
            )
        selected = (
            max(candidates, key=lambda candidate: candidate.score)
            if self.strategy is MockSelectionStrategy.HIGHEST_SCORE
            else candidates[0]
        )
        confidence = float(selected.score)
        return ExternalBaselineOutput(
            action=DecisionAction.EXECUTE_GRASP,
            selected_candidate_id=selected.candidate_id,
            confidence=confidence,
            risk_estimation=float(1.0 - confidence),
            reason=f"mock_{self.strategy.value}",
            diagnostics={"strategy": self.strategy.value},
        )


MOCK_EXTERNAL_BASELINE_METADATA = AlgorithmMetadata(
    algorithm_id=MOCK_EXTERNAL_BASELINE_ID,
    name="Mock External Baseline",
    version="v0.1",
    type=AlgorithmType.EXTERNAL_BASELINE,
    description="Minimal test-only external baseline for adapter verification.",
    status=AlgorithmStatus.PROTOTYPE,
    source="codex://threads/01a0a809-336e-7983-a31d-d3e73fe7f635",
    created_time="2026-09-16T00:00:00+08:00",
    blueprint_reference="external.mock.v0_1",
    provider_id=EXTERNAL_BASELINE_PROVIDER_ID,
    decision_contract=INTELLIGENCE_DECISION_SCHEMA_VERSION,
    stages=("input_conversion", "external_algorithm", "output_conversion"),
    capabilities=("candidate_selection",),
    license="Test-Only",
    repository="mock://xiezhi/mock-external-baseline-v0.1",
)


def create_mock_external_baseline_provider() -> ExternalBaselineAdapter:
    return ExternalBaselineAdapter(
        MOCK_EXTERNAL_BASELINE_METADATA,
        MockExternalBaseline(),
    )


__all__ = [
    "EXTERNAL_BASELINE_PROVIDER_ID",
    "MOCK_EXTERNAL_BASELINE_ID",
    "MOCK_EXTERNAL_BASELINE_METADATA",
    "ExternalAlgorithm",
    "ExternalBaselineAdapter",
    "ExternalBaselineInput",
    "ExternalBaselineOutput",
    "ExternalCandidateInput",
    "MockExternalBaseline",
    "MockSelectionStrategy",
    "create_mock_external_baseline_provider",
]
