"""Stable, UI-agnostic visualization projections for Xiezhi decision data."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .arena import ResultRecord
from .contracts import AlgorithmDecision
from .registry import AlgorithmRegistry


XIEZHI_DASHBOARD_SCHEMA_VERSION = "gongshu.xiezhi-dashboard/v1"


def _mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class DecisionRuntimeView:
    current_algorithm: str
    algorithm_version: str
    current_action: str
    selected_candidate: str | None
    confidence: float | None
    uncertainty: tuple[str, ...]
    risk: float | None
    reason: str

    def public_metadata(self) -> dict[str, Any]:
        return {
            "current_algorithm": self.current_algorithm,
            "algorithm_version": self.algorithm_version,
            "current_action": self.current_action,
            "selected_candidate": self.selected_candidate,
            "confidence": self.confidence,
            "uncertainty": list(self.uncertainty),
            "risk": self.risk,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DecisionEngineView:
    algorithm_metadata: Mapping[str, Any]
    algorithm_type: str
    algorithm_version: str
    algorithm_status: str
    blueprint_reference: str
    blueprint: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "algorithm_metadata", _mapping(self.algorithm_metadata))
        if self.blueprint is not None:
            object.__setattr__(self, "blueprint", _mapping(self.blueprint))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "algorithm_metadata": dict(self.algorithm_metadata),
            "algorithm_type": self.algorithm_type,
            "algorithm_version": self.algorithm_version,
            "algorithm_status": self.algorithm_status,
            "blueprint_reference": self.blueprint_reference,
            "blueprint": None if self.blueprint is None else dict(self.blueprint),
        }


@dataclass(frozen=True, slots=True)
class DecisionEvidenceView:
    selected_candidate: str | None
    positive_factors: Mapping[str, Any]
    negative_factors: Mapping[str, Any]
    risk_information: Mapping[str, Any]
    uncertainty_information: Mapping[str, Any]
    diagnostics: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "positive_factors",
            "negative_factors",
            "risk_information",
            "uncertainty_information",
            "diagnostics",
        ):
            object.__setattr__(self, name, _mapping(getattr(self, name)))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "selected_candidate": self.selected_candidate,
            "positive_factors": dict(self.positive_factors),
            "negative_factors": dict(self.negative_factors),
            "risk_information": dict(self.risk_information),
            "uncertainty_information": dict(self.uncertainty_information),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class DecisionHistoryEntry:
    experiment_id: str | None
    algorithm: Mapping[str, Any]
    decision_result: Mapping[str, Any] | None
    validation_result: Mapping[str, Any]
    success: bool
    failure_reason: str | None
    timestamp: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "algorithm", _mapping(self.algorithm))
        if self.decision_result is not None:
            object.__setattr__(self, "decision_result", _mapping(self.decision_result))
        object.__setattr__(self, "validation_result", _mapping(self.validation_result))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "algorithm": dict(self.algorithm),
            "decision_result": (
                None if self.decision_result is None else dict(self.decision_result)
            ),
            "validation_result": dict(self.validation_result),
            "success": self.success,
            "failure_reason": self.failure_reason,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class XiezhiDashboardState:
    runtime: DecisionRuntimeView
    engine: DecisionEngineView
    evidence: DecisionEvidenceView
    history: tuple[DecisionHistoryEntry, ...]
    schema_version: str = XIEZHI_DASHBOARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "history", tuple(self.history))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "runtime": self.runtime.public_metadata(),
            "engine": self.engine.public_metadata(),
            "evidence": self.evidence.public_metadata(),
            "history": [entry.public_metadata() for entry in self.history],
        }


class VisualizationDataProvider:
    """Project authoritative Registry, Decision, Blueprint, and Arena records for UI."""

    def __init__(self, registry: AlgorithmRegistry) -> None:
        if not isinstance(registry, AlgorithmRegistry):
            raise TypeError("VisualizationDataProvider requires AlgorithmRegistry")
        self._registry = registry

    def build(
        self,
        decision: AlgorithmDecision,
        arena_records: Iterable[ResultRecord] = (),
    ) -> XiezhiDashboardState:
        if not isinstance(decision, AlgorithmDecision):
            raise TypeError("dashboard runtime requires AlgorithmDecision v1")
        metadata = self._registry.query_algorithm(decision.algorithm_id)
        if metadata is None:
            raise ValueError(
                f"dashboard algorithm is not registered: {decision.algorithm_id}"
            )
        blueprint = self._registry.query_blueprint(decision.algorithm_id)
        runtime = DecisionRuntimeView(
            current_algorithm=metadata.name,
            algorithm_version=metadata.version,
            current_action=decision.action.value,
            selected_candidate=decision.selected_candidate_id,
            confidence=decision.confidence,
            uncertainty=decision.uncertainty,
            risk=decision.risk_estimation,
            reason=decision.reason,
        )
        engine = DecisionEngineView(
            algorithm_metadata=metadata.public_metadata(),
            algorithm_type=metadata.type.value,
            algorithm_version=metadata.version,
            algorithm_status=metadata.status.value,
            blueprint_reference=metadata.blueprint_reference,
            blueprint=None if blueprint is None else blueprint.public_metadata(),
        )
        diagnostics = dict(decision.diagnostics)
        candidate_evaluations = diagnostics.get("candidate_evaluations", [])
        selected_evaluation = next(
            (
                candidate
                for candidate in candidate_evaluations
                if candidate.get("candidate_id") == decision.selected_candidate_id
            ),
            None,
        )
        risk_assessment = diagnostics.get("risk_assessment")
        evidence = DecisionEvidenceView(
            selected_candidate=decision.selected_candidate_id,
            positive_factors={
                "confidence": decision.confidence,
                "selected_candidate_evaluation": selected_evaluation,
            },
            negative_factors={
                "risk_estimation": decision.risk_estimation,
                "uncertainty": list(decision.uncertainty),
            },
            risk_information={
                "value": decision.risk_estimation,
                "type": "HEURISTIC_UNCALIBRATED",
                "assessment": risk_assessment,
            },
            uncertainty_information={
                "items": list(decision.uncertainty),
                "count": len(decision.uncertainty),
            },
            diagnostics=diagnostics,
        )
        history = tuple(self._history_entry(record) for record in arena_records)
        return XiezhiDashboardState(runtime, engine, evidence, history)

    @staticmethod
    def _history_entry(record: ResultRecord) -> DecisionHistoryEntry:
        if not isinstance(record, ResultRecord):
            raise TypeError("dashboard history requires Arena ResultRecord values")
        decision = record.decision_output
        return DecisionHistoryEntry(
            experiment_id=record.metadata.get("experiment_id"),
            algorithm={
                "algorithm_id": (
                    record.metadata.get("algorithm_id")
                    if decision is None
                    else decision.algorithm_id
                ),
                "algorithm_version": record.metadata.get("algorithm_version"),
            },
            decision_result=(
                None if decision is None else decision.public_metadata()
            ),
            validation_result=record.validation_result,
            success=record.success,
            failure_reason=record.failure_reason,
            timestamp=record.created_time,
        )


__all__ = [
    "XIEZHI_DASHBOARD_SCHEMA_VERSION",
    "DecisionEngineView",
    "DecisionEvidenceView",
    "DecisionHistoryEntry",
    "DecisionRuntimeView",
    "VisualizationDataProvider",
    "XiezhiDashboardState",
]
