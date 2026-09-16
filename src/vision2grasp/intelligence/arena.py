"""Backend-only Algorithm Arena experiment and record foundations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from time import perf_counter
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from .contracts import AlgorithmDecision, AlgorithmObservation
from .registry import AlgorithmRegistry


ARENA_EXPERIMENT_SCHEMA_VERSION = "gongshu.algorithm-arena-experiment/v1"
ARENA_ALGORITHM_RUN_SCHEMA_VERSION = "gongshu.algorithm-arena-run/v1"
ARENA_RESULT_RECORD_SCHEMA_VERSION = "gongshu.algorithm-arena-result/v1"


def _validate_timestamp(value: str, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")


def _created_time() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArenaExperimentStatus(str, Enum):
    CREATED = "Created"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    ARCHIVED = "Archived"


@dataclass(frozen=True, slots=True)
class ArenaAlgorithmReference:
    algorithm_id: str
    algorithm_version: str

    def __post_init__(self) -> None:
        if not self.algorithm_id.strip() or not self.algorithm_version.strip():
            raise ValueError("Arena algorithm identity must not be empty")

    def public_metadata(self) -> dict[str, str]:
        return {
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
        }


@dataclass(frozen=True, slots=True)
class ArenaExperiment:
    experiment_id: str
    scene_id: str
    candidate_pool_id: str
    algorithms: tuple[ArenaAlgorithmReference, ...]
    created_time: str
    status: ArenaExperimentStatus
    validation_environment_id: str = "gongshu.validation.default"

    def __post_init__(self) -> None:
        for name in (
            "experiment_id",
            "scene_id",
            "candidate_pool_id",
            "validation_environment_id",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        algorithms = tuple(self.algorithms)
        identities = {
            (algorithm.algorithm_id, algorithm.algorithm_version)
            for algorithm in algorithms
        }
        if not algorithms or len(identities) != len(algorithms):
            raise ValueError("Arena algorithms must be present and unique")
        _validate_timestamp(self.created_time, "created_time")
        object.__setattr__(self, "algorithms", algorithms)
        object.__setattr__(self, "status", ArenaExperimentStatus(self.status))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": ARENA_EXPERIMENT_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "scene_id": self.scene_id,
            "candidate_pool_id": self.candidate_pool_id,
            "validation_environment_id": self.validation_environment_id,
            "algorithms": [algorithm.public_metadata() for algorithm in self.algorithms],
            "created_time": self.created_time,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class AlgorithmRun:
    algorithm_id: str
    algorithm_version: str
    input_reference: str
    decision_output: AlgorithmDecision
    execution_time: float
    created_time: str
    run_id: str = field(default_factory=lambda: f"arena-run-{uuid4().hex[:16]}")
    experiment_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("algorithm_id", "algorithm_version", "input_reference", "run_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if not isinstance(self.decision_output, AlgorithmDecision):
            raise TypeError("decision_output must use AlgorithmDecision v1")
        if self.decision_output.algorithm_id != self.algorithm_id:
            raise ValueError("Algorithm Run identity does not match its decision output")
        if not isfinite(self.execution_time) or self.execution_time < 0:
            raise ValueError("execution_time must be finite and non-negative")
        _validate_timestamp(self.created_time, "created_time")

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": ARENA_ALGORITHM_RUN_SCHEMA_VERSION,
            "run_id": self.run_id,
            "experiment_id": self.experiment_id,
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "input_reference": self.input_reference,
            "decision_output": self.decision_output.public_metadata(),
            "execution_time": self.execution_time,
            "created_time": self.created_time,
        }


@dataclass(frozen=True, slots=True)
class ResultRecord:
    success: bool
    failure_reason: str | None
    validation_result: Mapping[str, Any]
    execution_time: float
    metadata: Mapping[str, Any]
    record_id: str = field(default_factory=lambda: f"arena-result-{uuid4().hex[:16]}")
    algorithm_run_id: str | None = None
    decision_output: AlgorithmDecision | None = None
    created_time: str = field(default_factory=_created_time)

    def __post_init__(self) -> None:
        if type(self.success) is not bool:
            raise TypeError("success must be bool")
        if self.success and self.failure_reason is not None:
            raise ValueError("successful results cannot have a failure_reason")
        if not self.success and not str(self.failure_reason or "").strip():
            raise ValueError("failed results require failure_reason")
        if not isfinite(self.execution_time) or self.execution_time < 0:
            raise ValueError("execution_time must be finite and non-negative")
        if not self.record_id.strip():
            raise ValueError("record_id must not be empty")
        if self.decision_output is not None and not isinstance(
            self.decision_output, AlgorithmDecision
        ):
            raise TypeError("ResultRecord decision_output must use AlgorithmDecision v1")
        _validate_timestamp(self.created_time, "created_time")
        object.__setattr__(
            self, "validation_result", MappingProxyType(dict(self.validation_result))
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": ARENA_RESULT_RECORD_SCHEMA_VERSION,
            "record_id": self.record_id,
            "algorithm_run_id": self.algorithm_run_id,
            "decision_output": (
                None
                if self.decision_output is None
                else self.decision_output.public_metadata()
            ),
            "created_time": self.created_time,
            "success": self.success,
            "failure_reason": self.failure_reason,
            "validation_result": dict(self.validation_result),
            "execution_time": self.execution_time,
            "metadata": dict(self.metadata),
        }


class ArenaResultStore:
    """Minimal in-memory record store; persistence policy remains outside Arena v1."""

    def __init__(self) -> None:
        self._records: dict[str, ResultRecord] = {}

    def save(self, record: ResultRecord) -> ResultRecord:
        if not isinstance(record, ResultRecord):
            raise TypeError("Arena result store accepts ResultRecord values")
        if record.record_id in self._records:
            raise ValueError(f"Arena result is already saved: {record.record_id}")
        self._records[record.record_id] = record
        return record

    def get(self, record_id: str) -> ResultRecord | None:
        return self._records.get(str(record_id).strip())

    def list(self) -> tuple[ResultRecord, ...]:
        return tuple(self._records.values())


class AlgorithmArenaBackend:
    """Run registered decision providers against one immutable Arena input."""

    def __init__(self, registry: AlgorithmRegistry) -> None:
        if not isinstance(registry, AlgorithmRegistry):
            raise TypeError("Algorithm Arena requires AlgorithmRegistry")
        self._registry = registry

    def algorithm_reference(self, algorithm_id: str) -> ArenaAlgorithmReference:
        metadata = self._registry.query_algorithm(algorithm_id)
        if metadata is None:
            raise ValueError(f"Arena algorithm is not registered: {algorithm_id}")
        if not self._registry.supports(metadata.provider_id, metadata.algorithm_id):
            raise ValueError(f"Arena algorithm has no runtime provider: {algorithm_id}")
        return ArenaAlgorithmReference(metadata.algorithm_id, metadata.version)

    def create_experiment(
        self,
        *,
        experiment_id: str,
        scene_id: str,
        candidate_pool_id: str,
        algorithms: tuple[ArenaAlgorithmReference, ...],
        validation_environment_id: str,
    ) -> ArenaExperiment:
        for reference in algorithms:
            registered = self.algorithm_reference(reference.algorithm_id)
            if registered != reference:
                raise ValueError("Arena algorithm version does not match Registry")
        return ArenaExperiment(
            experiment_id=experiment_id,
            scene_id=scene_id,
            candidate_pool_id=candidate_pool_id,
            algorithms=algorithms,
            created_time=_created_time(),
            status=ArenaExperimentStatus.CREATED,
            validation_environment_id=validation_environment_id,
        )

    def run_algorithm(
        self,
        experiment: ArenaExperiment,
        algorithm: ArenaAlgorithmReference,
        observation: AlgorithmObservation,
        *,
        input_reference: str,
    ) -> AlgorithmRun:
        if algorithm not in experiment.algorithms:
            raise ValueError("algorithm is not part of this Arena experiment")
        if input_reference != experiment.candidate_pool_id:
            raise ValueError("Arena run input must reference the fixed candidate pool")
        if experiment.status not in {
            ArenaExperimentStatus.CREATED,
            ArenaExperimentStatus.RUNNING,
        }:
            raise ValueError("Arena experiment is not runnable")
        metadata = self._registry.query_algorithm(algorithm.algorithm_id)
        if metadata is None or metadata.version != algorithm.algorithm_version:
            raise ValueError("Arena algorithm identity is not available in Registry")
        provider = self._registry.create(metadata.provider_id, metadata.algorithm_id)
        started = perf_counter()
        decision = provider.decide(observation)
        elapsed = perf_counter() - started
        return AlgorithmRun(
            algorithm_id=metadata.algorithm_id,
            algorithm_version=metadata.version,
            input_reference=input_reference,
            decision_output=decision,
            execution_time=elapsed,
            created_time=_created_time(),
            experiment_id=experiment.experiment_id,
        )

    @staticmethod
    def record_result(
        run: AlgorithmRun,
        *,
        success: bool,
        failure_reason: str | None,
        validation_result: Mapping[str, Any],
        execution_time: float,
        metadata: Mapping[str, Any],
    ) -> ResultRecord:
        return ResultRecord(
            success=success,
            failure_reason=failure_reason,
            validation_result=validation_result,
            execution_time=execution_time,
            metadata=metadata,
            algorithm_run_id=run.run_id,
            decision_output=run.decision_output,
        )


__all__ = [
    "ARENA_ALGORITHM_RUN_SCHEMA_VERSION",
    "ARENA_EXPERIMENT_SCHEMA_VERSION",
    "ARENA_RESULT_RECORD_SCHEMA_VERSION",
    "AlgorithmArenaBackend",
    "AlgorithmRun",
    "ArenaAlgorithmReference",
    "ArenaExperiment",
    "ArenaExperimentStatus",
    "ArenaResultStore",
    "ResultRecord",
]
