"""Gongshu-owned registry for interchangeable algorithm providers."""

from __future__ import annotations

from collections.abc import Callable

from .blueprint import AlgorithmMetadata
from .providers import AlgorithmProvider, BaselineDecisionProvider, XiezhiDecisionProvider


ProviderFactory = Callable[[], AlgorithmProvider]


class AlgorithmRegistry:
    """Resolve provider/algorithm pairs without giving algorithms runtime ownership."""

    def __init__(self) -> None:
        self._factories: dict[tuple[str, str], ProviderFactory] = {}
        self._metadata: dict[tuple[str, str], AlgorithmMetadata] = {}

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
        self._factories[key] = factory
        if metadata is not None:
            self._metadata[key] = metadata

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


def default_algorithm_registry(*, include_xiezhi: bool) -> AlgorithmRegistry:
    registry = AlgorithmRegistry()
    registry.register("gongshu", "baseline_topk", BaselineDecisionProvider)
    if include_xiezhi:
        registry.register(
            "xiezhi",
            XiezhiDecisionProvider.algorithm_id,
            XiezhiDecisionProvider,
            metadata=XiezhiDecisionProvider.metadata,
        )
    return registry


__all__ = ["AlgorithmRegistry", "ProviderFactory", "default_algorithm_registry"]
