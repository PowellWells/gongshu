"""Non-UI contracts for describing algorithm structure and future blueprints."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping


ALGORITHM_BLUEPRINT_SCHEMA_VERSION = "gongshu.algorithm-blueprint/v1"
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}")


@dataclass(frozen=True, slots=True)
class BlueprintStage:
    stage_id: str
    name: str
    input_contract: str
    output_contract: str
    description: str

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.stage_id):
            raise ValueError("stage_id must be a lowercase identifier")
        for field_name in ("name", "input_contract", "output_contract", "description"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")

    def public_metadata(self) -> dict[str, str]:
        return {
            "stage_id": self.stage_id,
            "name": self.name,
            "input_contract": self.input_contract,
            "output_contract": self.output_contract,
            "description": self.description,
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
    provider_id: str
    algorithm_id: str
    display_name: str
    version: str
    decision_contract: str
    blueprint_id: str
    stages: tuple[str, ...]
    capabilities: tuple[str, ...]
    description: str

    def __post_init__(self) -> None:
        for field_name in (
            "provider_id",
            "algorithm_id",
            "display_name",
            "version",
            "decision_contract",
            "blueprint_id",
            "description",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        if not _IDENTIFIER.fullmatch(self.provider_id):
            raise ValueError("provider_id must be a lowercase identifier")
        if not _IDENTIFIER.fullmatch(self.algorithm_id):
            raise ValueError("algorithm_id must be a lowercase identifier")
        object.__setattr__(self, "stages", tuple(self.stages))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "provider": self.provider_id,
            "algorithm": self.algorithm_id,
            "display_name": self.display_name,
            "version": self.version,
            "decision_contract": self.decision_contract,
            "blueprint_id": self.blueprint_id,
            "blueprint_schema_version": ALGORITHM_BLUEPRINT_SCHEMA_VERSION,
            "stages": list(self.stages),
            "capabilities": list(self.capabilities),
            "description": self.description,
        }


__all__ = [
    "ALGORITHM_BLUEPRINT_SCHEMA_VERSION",
    "AlgorithmBlueprint",
    "AlgorithmMetadata",
    "BlueprintStage",
]
