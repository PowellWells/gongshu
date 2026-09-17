"""Gongshu-owned registry for interchangeable algorithm providers."""

from __future__ import annotations

from collections.abc import Callable

from .blueprint import (
    AlgorithmBlueprint,
    AlgorithmMetadata,
    AlgorithmStatus,
    AlgorithmType,
)
from .external_baseline import (
    MOCK_EXTERNAL_BASELINE_METADATA,
    create_mock_external_baseline_provider,
)
from .providers import AlgorithmProvider, BaselineDecisionProvider, XiezhiDecisionProvider


ProviderFactory = Callable[[], AlgorithmProvider]


class AlgorithmRegistry:
    """Resolve provider/algorithm pairs without giving algorithms runtime ownership."""

    def __init__(self) -> None:
        self._factories: dict[tuple[str, str], ProviderFactory] = {}
        self._metadata: dict[tuple[str, str], AlgorithmMetadata] = {}
        self._metadata_by_id: dict[str, AlgorithmMetadata] = {}
        self._metadata_by_name_version: dict[tuple[str, str], AlgorithmMetadata] = {}
        self._blueprints_by_id: dict[str, AlgorithmBlueprint] = {}

    @staticmethod
    def _name_version_key(name: str, version: str) -> tuple[str, str]:
        return (str(name).strip().casefold(), str(version).strip().casefold())

    def _register_metadata(self, metadata: AlgorithmMetadata) -> None:
        if not isinstance(metadata, AlgorithmMetadata):
            raise TypeError("metadata must be AlgorithmMetadata")
        if metadata.algorithm_id in self._metadata_by_id:
            raise ValueError(f"algorithm ID is already registered: {metadata.algorithm_id}")
        name_version = self._name_version_key(metadata.name, metadata.version)
        if name_version in self._metadata_by_name_version:
            raise ValueError(
                f"algorithm name/version is already registered: {metadata.name} {metadata.version}"
            )
        runtime_key = (metadata.provider_id, metadata.algorithm_id)
        self._metadata[runtime_key] = metadata
        self._metadata_by_id[metadata.algorithm_id] = metadata
        self._metadata_by_name_version[name_version] = metadata

    def register(
        self,
        provider_id: str,
        algorithm_id: str,
        factory: ProviderFactory,
        *,
        metadata: AlgorithmMetadata | None = None,
    ) -> None:
        key = (provider_id.strip(), algorithm_id.strip())
        if not all(key) or not callable(factory):
            raise ValueError("provider, algorithm, and factory must be valid")
        if key in self._factories:
            raise ValueError(f"algorithm provider is already registered: {key}")
        if metadata is not None and (metadata.provider_id, metadata.algorithm_id) != key:
            raise ValueError("algorithm metadata identity does not match its registry entry")
        if metadata is not None:
            self._register_metadata(metadata)
        self._factories[key] = factory

    def register_algorithm(
        self,
        metadata: AlgorithmMetadata,
        factory: ProviderFactory | None = None,
        *,
        blueprint: AlgorithmBlueprint | None = None,
    ) -> None:
        """Register formal identity metadata, optionally with a runtime provider."""

        if blueprint is not None and (
            blueprint.provider_id != metadata.provider_id
            or blueprint.algorithm_id != metadata.algorithm_id
            or blueprint.algorithm_version != metadata.version
            or blueprint.blueprint_id != metadata.blueprint_reference
        ):
            raise ValueError("algorithm blueprint identity does not match metadata")
        if factory is None:
            self._register_metadata(metadata)
        else:
            self.register(
                metadata.provider_id,
                metadata.algorithm_id,
                factory,
                metadata=metadata,
            )
        if blueprint is not None:
            self._blueprints_by_id[metadata.algorithm_id] = blueprint

    def create(self, provider_id: str, algorithm_id: str) -> AlgorithmProvider:
        key = (provider_id, algorithm_id)
        factory = self._factories.get(key)
        if factory is None:
            raise ValueError(f"algorithm provider is not registered: {key}")
        provider = factory()
        if provider.provider_id != provider_id or provider.algorithm_id != algorithm_id:
            raise TypeError("algorithm provider identity does not match its registry entry")
        return provider

    def supports(self, provider_id: str, algorithm_id: str) -> bool:
        return (provider_id, algorithm_id) in self._factories

    def entries(self) -> tuple[dict[str, object], ...]:
        return tuple(
            (
                {"provider": provider, "algorithm": algorithm}
                if (provider, algorithm) not in self._metadata
                else self._metadata[(provider, algorithm)].public_metadata()
            )
            for provider, algorithm in self._factories
        )

    def metadata(self, provider_id: str, algorithm_id: str) -> dict[str, object] | None:
        metadata = self._metadata.get((provider_id, algorithm_id))
        return None if metadata is None else metadata.public_metadata()

    def query_algorithm(self, algorithm_id: str) -> AlgorithmMetadata | None:
        return self._metadata_by_id.get(str(algorithm_id).strip())

    def provider_id_for(self, algorithm_id: str) -> str | None:
        """Resolve a unique runtime provider from an algorithm ID."""

        normalized = str(algorithm_id).strip()
        metadata = self.query_algorithm(normalized)
        if metadata is not None:
            return metadata.provider_id
        providers = {
            provider_id
            for provider_id, registered_algorithm_id in self._factories
            if registered_algorithm_id == normalized
        }
        if len(providers) > 1:
            raise ValueError(f"algorithm ID has multiple providers: {normalized}")
        return next(iter(providers), None)

    def query_blueprint(self, algorithm_id: str) -> AlgorithmBlueprint | None:
        return self._blueprints_by_id.get(str(algorithm_id).strip())

    def get_by_name_version(
        self, name: str, version: str
    ) -> AlgorithmMetadata | None:
        return self._metadata_by_name_version.get(self._name_version_key(name, version))

    def list_algorithms(
        self,
        *,
        algorithm_type: AlgorithmType | str | None = None,
        status: AlgorithmStatus | str | None = None,
    ) -> tuple[AlgorithmMetadata, ...]:
        selected_type = None if algorithm_type is None else AlgorithmType(algorithm_type)
        selected_status = None if status is None else AlgorithmStatus(status)
        return tuple(
            metadata
            for metadata in self._metadata_by_id.values()
            if (selected_type is None or metadata.type is selected_type)
            and (selected_status is None or metadata.status is selected_status)
        )


def default_algorithm_registry(
    *,
    include_xiezhi: bool,
    include_mock_external: bool = False,
) -> AlgorithmRegistry:
    registry = AlgorithmRegistry()
    registry.register("gongshu", "baseline_topk", BaselineDecisionProvider)
    if include_mock_external:
        registry.register_algorithm(
            MOCK_EXTERNAL_BASELINE_METADATA,
            create_mock_external_baseline_provider,
        )
    if include_xiezhi:
        registry.register_algorithm(
            XiezhiDecisionProvider.metadata,
            XiezhiDecisionProvider,
            blueprint=XiezhiDecisionProvider.blueprint,
        )
    return registry


__all__ = ["AlgorithmRegistry", "ProviderFactory", "default_algorithm_registry"]
