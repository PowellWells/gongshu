"""Gongshu-owned registry for interchangeable algorithm providers."""

from __future__ import annotations

from collections.abc import Callable

from .providers import AlgorithmProvider, BaselineDecisionProvider, XiezhiDecisionProvider


ProviderFactory = Callable[[], AlgorithmProvider]


class AlgorithmRegistry:
    """Resolve provider/algorithm pairs without giving algorithms runtime ownership."""

    def __init__(self) -> None:
        self._factories: dict[tuple[str, str], ProviderFactory] = {}

    def register(
        self, provider_id: str, algorithm_id: str, factory: ProviderFactory
    ) -> None:
        key = (provider_id.strip(), algorithm_id.strip())
        if not all(key) or not callable(factory):
            raise ValueError("provider, algorithm, and factory must be valid")
        if key in self._factories:
            raise ValueError(f"algorithm provider is already registered: {key}")
        self._factories[key] = factory

    def create(self, provider_id: str, algorithm_id: str) -> AlgorithmProvider:
        key = (provider_id, algorithm_id)
        factory = self._factories.get(key)
        if factory is None:
            raise ValueError(f"algorithm provider is not registered: {key}")
        provider = factory()
        if provider.provider_id != provider_id or provider.algorithm_id != algorithm_id:
            raise TypeError("algorithm provider identity does not match its registry entry")
        return provider

    def entries(self) -> tuple[dict[str, str], ...]:
        return tuple(
            {"provider": provider, "algorithm": algorithm}
            for provider, algorithm in self._factories
        )


def default_algorithm_registry(*, include_xiezhi: bool) -> AlgorithmRegistry:
    registry = AlgorithmRegistry()
    registry.register("gongshu", "baseline_topk", BaselineDecisionProvider)
    if include_xiezhi:
        registry.register("xiezhi", "rule_based", XiezhiDecisionProvider)
    return registry


__all__ = ["AlgorithmRegistry", "ProviderFactory", "default_algorithm_registry"]
