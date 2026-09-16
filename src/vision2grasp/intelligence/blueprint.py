"""Non-UI contracts for describing algorithm structure and future blueprints."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping


ALGORITHM_BLUEPRINT_SCHEMA_VERSION = "gongshu.algorithm-blueprint/v1"
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}")


class AlgorithmType(str, Enum):
    EXTERNAL_BASELINE = "External Baseline"
    XIEZHI_ALGORITHM = "Xiezhi Algorithm"


class AlgorithmStatus(str, Enum):
    PROTOTYPE = "Prototype"
    EXPERIMENTAL = "Experimental"
    VALIDATED = "Validated"
    ARCHIVED = "Archived"


@dataclass(frozen=True, slots=True)
class BlueprintStage:
    stage_id: str
    name: str
    input_contract: str
    output_contract: str
    description: str
    module: str | None = None
    function: str | None = None

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.stage_id):
            raise ValueError("stage_id must be a lowercase identifier")
        for field_name in ("name", "input_contract", "output_contract", "description"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if (self.module is None) != (self.function is None):
            raise ValueError("blueprint stage module and function must be provided together")
        if self.module is not None:
            object.__setattr__(self, "module", str(self.module).strip())
            object.__setattr__(self, "function", str(self.function).strip())
            if not self.module or not self.function:
                raise ValueError("blueprint stage module and function must not be empty")

    def public_metadata(self) -> dict[str, str | None]:
        return {
            "stage_id": self.stage_id,
            "name": self.name,
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
            "description": self.description,
            "module": self.module,
            "function": self.function,
        }


@dataclass(frozen=True, slots=True)
class AlgorithmBlueprint:
    """Serializable structure only; it does not execute algorithms or drive UI."""

    blueprint_id: str
    provider_id: str
    algorithm_id: str
    algorithm_version: str
    stages: tuple[BlueprintStage, ...]
    edges: tuple[tuple[str, str], ...]
    parameters: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ALGORITHM_BLUEPRINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in ("blueprint_id", "provider_id", "algorithm_id", "algorithm_version"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        stages = tuple(self.stages)
        stage_ids = {stage.stage_id for stage in stages}
        if not stages or len(stage_ids) != len(stages):
            raise ValueError("blueprint stages must be present and unique")
        edges = tuple((str(source), str(target)) for source, target in self.edges)
        if any(source not in stage_ids or target not in stage_ids for source, target in edges):
            raise ValueError("blueprint edges must reference declared stages")
        object.__setattr__(self, "stages", stages)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "blueprint_id": self.blueprint_id,
            "provider": self.provider_id,
            "algorithm": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "stages": [stage.public_metadata() for stage in self.stages],
            "edges": [list(edge) for edge in self.edges],
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class AlgorithmMetadata:
    algorithm_id: str
    name: str
    version: str
    type: AlgorithmType
    description: str
    status: AlgorithmStatus
    source: str
    created_time: str
    blueprint_reference: str
    provider_id: str
    decision_contract: str
    stages: tuple[str, ...]
    capabilities: tuple[str, ...]
    license: str | None = None
    repository: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "algorithm_id",
            "name",
            "version",
            "description",
            "source",
            "created_time",
            "blueprint_reference",
            "provider_id",
            "decision_contract",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if not _IDENTIFIER.fullmatch(self.provider_id):
            raise ValueError("provider_id must be a lowercase identifier")
        if not _IDENTIFIER.fullmatch(self.algorithm_id):
            raise ValueError("algorithm_id must be a lowercase identifier")
        try:
            algorithm_type = AlgorithmType(self.type)
        except ValueError as error:
            raise ValueError("unsupported algorithm type") from error
        try:
            status = AlgorithmStatus(self.status)
        except ValueError as error:
            raise ValueError("unsupported algorithm status") from error
        try:
            created = datetime.fromisoformat(self.created_time.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("created_time must be an ISO 8601 timestamp") from error
        if created.tzinfo is None:
            raise ValueError("created_time must include a timezone")
        object.__setattr__(self, "type", algorithm_type)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "stages", tuple(self.stages))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "license", None if self.license is None else str(self.license).strip())
        object.__setattr__(
            self,
            "repository",
            None if self.repository is None else str(self.repository).strip(),
        )

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def blueprint_id(self) -> str:
        return self.blueprint_reference

    def public_metadata(self) -> dict[str, Any]:
        return {
            "algorithm_id": self.algorithm_id,
            "name": self.name,
            "version": self.version,
            "type": self.type.value,
            "description": self.description,
            "status": self.status.value,
            "source": self.source,
            "created_time": self.created_time,
            "blueprint_reference": self.blueprint_reference,
            "license": self.license,
            "repository": self.repository,
            "provider": self.provider_id,
            "algorithm": self.algorithm_id,
            "display_name": self.display_name,
            "decision_contract": self.decision_contract,
            "blueprint_id": self.blueprint_id,
            "blueprint_schema_version": ALGORITHM_BLUEPRINT_SCHEMA_VERSION,
            "stages": list(self.stages),
            "capabilities": list(self.capabilities),
        }


__all__ = [
    "ALGORITHM_BLUEPRINT_SCHEMA_VERSION",
    "AlgorithmBlueprint",
    "AlgorithmMetadata",
    "AlgorithmStatus",
    "AlgorithmType",
    "BlueprintStage",
]
