"""Sequential backend runner for registered Algorithm Arena participants."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from types import MappingProxyType
from typing import Any, Protocol

from .arena import (
    AlgorithmArenaBackend,
    AlgorithmRun,
    ArenaExperiment,
    ArenaExperimentStatus,
    ArenaResultStore,
    ResultRecord,
)
from .contracts import AlgorithmObservation


ARENA_RUNNER_EXECUTION_SCHEMA_VERSION = "gongshu.algorithm-arena-execution/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class ArenaValidationOutcome:
    success: bool
    failure_reason: str | None
    validation_result: Mapping[str, Any]
    execution_time: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.success) is not bool:
            raise TypeError("Arena validation success must be bool")
        if self.success and self.failure_reason is not None:
            raise ValueError("successful validation cannot have failure_reason")
        if not self.success and not str(self.failure_reason or "").strip():
            raise ValueError("failed validation requires failure_reason")
        if not isfinite(self.execution_time) or self.execution_time < 0:
            raise ValueError("validation execution_time must be finite and non-negative")
        object.__setattr__(
            self, "validation_result", MappingProxyType(dict(self.validation_result))
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class ArenaValidation(Protocol):
    def validate(
        self,
        experiment: ArenaExperiment,
        run: AlgorithmRun,
    ) -> ArenaValidationOutcome: ...


class MockArenaValidation:
    """Decision-level test validation; it does not simulate or control a robot."""

    def __init__(self, environment_id: str) -> None:
        if not str(environment_id).strip():
            raise ValueError("Mock validation environment_id must not be empty")
        self.environment_id = str(environment_id).strip()

    def validate(
        self,
        experiment: ArenaExperiment,
        run: AlgorithmRun,
    ) -> ArenaValidationOutcome:
        if experiment.validation_environment_id != self.environment_id:
            raise ValueError("Mock validation environment does not match Arena experiment")
        decision = run.decision_output
        success = decision.authorizes_execution
        return ArenaValidationOutcome(
            success=success,
            failure_reason=None if success else "DECISION_DID_NOT_AUTHORIZE_EXECUTION",
            validation_result={
                "validator": "MockArenaValidation",
                "environment_id": self.environment_id,
                "decision_id": decision.decision_id,
                "action": decision.action.value,
                "selected_candidate_id": decision.selected_candidate_id,
                "status": "SUCCESS" if success else "FAILED",
            },
            execution_time=0.0,
            metadata={"mock_validation": True},
        )


class ArenaRunStore:
    """In-memory AlgorithmRun store used by the backend foundation."""

    def __init__(self) -> None:
        self._runs: dict[str, AlgorithmRun] = {}

    def save(self, run: AlgorithmRun) -> AlgorithmRun:
        if not isinstance(run, AlgorithmRun):
            raise TypeError("Arena run store accepts AlgorithmRun values")
        if run.run_id in self._runs:
            raise ValueError(f"Arena run is already saved: {run.run_id}")
        self._runs[run.run_id] = run
        return run

    def get(self, run_id: str) -> AlgorithmRun | None:
        return self._runs.get(str(run_id).strip())

    def list(self) -> tuple[AlgorithmRun, ...]:
        return tuple(self._runs.values())


@dataclass(frozen=True, slots=True)
class ArenaExecution:
    experiment_id: str
    algorithm_runs: tuple[AlgorithmRun, ...]
    result_records: tuple[ResultRecord, ...]
    started_time: str
    completed_time: str
    status: ArenaExperimentStatus

    def __post_init__(self) -> None:
        runs = tuple(self.algorithm_runs)
        results = tuple(self.result_records)
        if not self.experiment_id.strip():
            raise ValueError("Arena execution experiment_id must not be empty")
        if not runs or len(runs) != len(results):
            raise ValueError("Arena execution requires one result per algorithm run")
        if len({run.run_id for run in runs}) != len(runs):
            raise ValueError("Arena execution run IDs must be unique")
        if len({run.decision_output.decision_id for run in runs}) != len(runs):
            raise ValueError("Arena algorithms must not share Decision results")
        object.__setattr__(self, "algorithm_runs", runs)
        object.__setattr__(self, "result_records", results)
        object.__setattr__(self, "status", ArenaExperimentStatus(self.status))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": ARENA_RUNNER_EXECUTION_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "algorithm_runs": [run.public_metadata() for run in self.algorithm_runs],
            "result_records": [record.public_metadata() for record in self.result_records],
            "started_time": self.started_time,
            "completed_time": self.completed_time,
            "status": self.status.value,
        }


class AlgorithmArenaRunner:
    """Execute every configured algorithm independently and save both record types."""

    def __init__(
        self,
        backend: AlgorithmArenaBackend,
        validation: ArenaValidation,
        *,
        run_store: ArenaRunStore | None = None,
        result_store: ArenaResultStore | None = None,
    ) -> None:
        if not isinstance(backend, AlgorithmArenaBackend):
            raise TypeError("AlgorithmArenaRunner requires AlgorithmArenaBackend")
        if not callable(getattr(validation, "validate", None)):
            raise TypeError("AlgorithmArenaRunner requires ArenaValidation")
        self._backend = backend
        self._validation = validation
        self.run_store = run_store or ArenaRunStore()
        self.result_store = result_store or ArenaResultStore()

    def run(
        self,
        experiment: ArenaExperiment,
        observation: AlgorithmObservation,
    ) -> ArenaExecution:
        if experiment.status not in {
            ArenaExperimentStatus.CREATED,
            ArenaExperimentStatus.RUNNING,
        }:
            raise ValueError("Arena experiment is not runnable")
        if not isinstance(observation, AlgorithmObservation):
            raise TypeError("Arena Runner requires AlgorithmObservation")
        started_time = _now()
        runs: list[AlgorithmRun] = []
        results: list[ResultRecord] = []
        decision_ids: set[str] = set()
        for algorithm in experiment.algorithms:
            run = self._backend.run_algorithm(
                experiment,
                algorithm,
                observation,
                input_reference=experiment.candidate_pool_id,
            )
            if run.decision_output.decision_id in decision_ids:
                raise RuntimeError("Arena algorithms returned a shared Decision result")
            decision_ids.add(run.decision_output.decision_id)
            self.run_store.save(run)
            validation = self._validation.validate(experiment, run)
            result = self._backend.record_result(
                run,
                success=validation.success,
                failure_reason=validation.failure_reason,
                validation_result=validation.validation_result,
                execution_time=validation.execution_time,
                metadata={
                    **dict(validation.metadata),
                    "experiment_id": experiment.experiment_id,
                    "scene_id": experiment.scene_id,
                    "candidate_pool_id": experiment.candidate_pool_id,
                    "validation_environment_id": experiment.validation_environment_id,
                    "algorithm_id": run.algorithm_id,
                    "algorithm_version": run.algorithm_version,
                },
            )
            self.result_store.save(result)
            runs.append(run)
            results.append(result)
        return ArenaExecution(
            experiment_id=experiment.experiment_id,
            algorithm_runs=tuple(runs),
            result_records=tuple(results),
            started_time=started_time,
            completed_time=_now(),
            status=ArenaExperimentStatus.COMPLETED,
        )


__all__ = [
    "ARENA_RUNNER_EXECUTION_SCHEMA_VERSION",
    "AlgorithmArenaRunner",
    "ArenaExecution",
    "ArenaRunStore",
    "ArenaValidation",
    "ArenaValidationOutcome",
    "MockArenaValidation",
]
