"""Runtime selection and loading for registered Decision Algorithms."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import threading
from types import MappingProxyType
from typing import Any, Mapping

from .contracts import AlgorithmDecision, AlgorithmObservation
from .providers import AlgorithmProvider
from .registry import AlgorithmRegistry


ACTIVE_ALGORITHM_SCHEMA_VERSION = "gongshu.active-algorithm/v1"


@dataclass(frozen=True, slots=True)
class ActiveAlgorithm:
    algorithm_id: str
    provider_id: str
    name: str
    version: str
    type: str
    status: str
    metadata: Mapping[str, Any]
    schema_version: str = ACTIVE_ALGORITHM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "algorithm_id",
            "provider_id",
            "name",
            "version",
            "type",
            "status",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "algorithm_id": self.algorithm_id,
            "provider": self.provider_id,
            "name": self.name,
            "version": self.version,
            "type": self.type,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


class AlgorithmLoader:
    """Load providers only through the platform-owned Algorithm Registry."""

    def __init__(self, registry: AlgorithmRegistry) -> None:
        if not isinstance(registry, AlgorithmRegistry):
            raise TypeError("AlgorithmLoader requires AlgorithmRegistry")
        self._registry = registry

    def load(self, algorithm_id: str) -> AlgorithmProvider:
        normalized = str(algorithm_id).strip()
        provider_id = self._registry.provider_id_for(normalized)
        if provider_id is None:
            raise ValueError(f"algorithm is not registered: {normalized}")
        provider = self._registry.create(provider_id, normalized)
        if not isinstance(provider, AlgorithmProvider):
            raise TypeError("loaded algorithm must implement AlgorithmProvider")
        return provider

    def decide(
        self,
        algorithm_id: str,
        observation: AlgorithmObservation,
    ) -> AlgorithmDecision:
        provider = self.load(algorithm_id)
        decision = provider.decide(observation)
        if not isinstance(decision, AlgorithmDecision):
            raise TypeError("Decision Algorithm must return AlgorithmDecision v1")
        if (
            decision.algorithm_id != provider.algorithm_id
            or decision.provider_id != provider.provider_id
        ):
            raise TypeError("AlgorithmDecision identity does not match loaded provider")
        return decision


class ActiveAlgorithmSelector:
    """Own the active algorithm ID and optionally persist it as JSON."""

    def __init__(
        self,
        registry: AlgorithmRegistry,
        default_algorithm_id: str,
        *,
        state_path: str | Path | None = None,
    ) -> None:
        if not isinstance(registry, AlgorithmRegistry):
            raise TypeError("ActiveAlgorithmSelector requires AlgorithmRegistry")
        self._registry = registry
        self._state_path = None if state_path is None else Path(state_path)
        self._lock = threading.RLock()
        self._active_algorithm_id = str(default_algorithm_id).strip()
        self._resolve(self._active_algorithm_id)
        restored = self._restore_algorithm_id()
        if restored is not None:
            self._active_algorithm_id = restored

    def _resolve(self, algorithm_id: str) -> ActiveAlgorithm:
        normalized = str(algorithm_id).strip()
        provider_id = self._registry.provider_id_for(normalized)
        if provider_id is None or not self._registry.supports(provider_id, normalized):
            raise ValueError(f"algorithm is not available: {normalized}")
        metadata = self._registry.query_algorithm(normalized)
        if metadata is None:
            public = {
                "algorithm_id": normalized,
                "provider": provider_id,
                "name": normalized,
                "version": "legacy",
                "type": "External Baseline",
                "status": "Validated",
            }
        else:
            public = metadata.public_metadata()
        return ActiveAlgorithm(
            algorithm_id=normalized,
            provider_id=provider_id,
            name=str(public["name"]),
            version=str(public["version"]),
            type=str(public["type"]),
            status=str(public["status"]),
            metadata=public,
        )

    def _restore_algorithm_id(self) -> str | None:
        if self._state_path is None or not self._state_path.is_file():
            return None
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != ACTIVE_ALGORITHM_SCHEMA_VERSION:
                return None
            algorithm_id = str(payload["algorithm_id"]).strip()
            self._resolve(algorithm_id)
            return algorithm_id
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _save(self, active: ActiveAlgorithm) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._state_path.with_suffix(f"{self._state_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(active.public_metadata(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self._state_path)

    def get_active(self) -> ActiveAlgorithm:
        with self._lock:
            return self._resolve(self._active_algorithm_id)

    def get_active_algorithm(self) -> ActiveAlgorithm:
        return self.get_active()

    def set_active(self, algorithm_id: str) -> ActiveAlgorithm:
        active = self._resolve(algorithm_id)
        with self._lock:
            self._save(active)
            self._active_algorithm_id = active.algorithm_id
            return active

    def set_active_algorithm(self, algorithm_id: str) -> ActiveAlgorithm:
        return self.set_active(algorithm_id)


class DecisionEngine:
    """Execute the active provider while exposing one stable decision interface."""

    def __init__(
        self,
        selector: ActiveAlgorithmSelector,
        loader: AlgorithmLoader,
    ) -> None:
        if not isinstance(selector, ActiveAlgorithmSelector):
            raise TypeError("DecisionEngine requires ActiveAlgorithmSelector")
        if not isinstance(loader, AlgorithmLoader):
            raise TypeError("DecisionEngine requires AlgorithmLoader")
        self._selector = selector
        self._loader = loader

    def active_algorithm(self) -> ActiveAlgorithm:
        return self._selector.get_active_algorithm()

    def set_active_algorithm(self, algorithm_id: str) -> ActiveAlgorithm:
        return self._selector.set_active_algorithm(algorithm_id)

    def decide(self, observation: AlgorithmObservation) -> AlgorithmDecision:
        return self._loader.decide(
            self._selector.get_active_algorithm().algorithm_id,
            observation,
        )


__all__ = [
    "ACTIVE_ALGORITHM_SCHEMA_VERSION",
    "ActiveAlgorithm",
    "ActiveAlgorithmSelector",
    "AlgorithmLoader",
    "DecisionEngine",
]
