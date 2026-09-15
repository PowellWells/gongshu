"""Feature-gated call path from Gongshu observation to Xiezhi decision."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .backend import MayflowerXiezhiDecisionBackend
from .contracts import (
    GongshuDecision,
    GongshuObservation,
    IntegrationResult,
    XiezhiAdapterConfig,
    XiezhiDecisionBackend,
)


LegacyFlow = Callable[[], Any]
DecisionExecution = Callable[[GongshuDecision], Any]


class GongshuXiezhiAdapter:
    """Keep the legacy path intact unless the optional extension is enabled."""

    def __init__(self, config: XiezhiAdapterConfig | None = None,
                 backend: XiezhiDecisionBackend | None = None) -> None:
        self.config = config or XiezhiAdapterConfig()
        self._backend = backend

    def run(self, observation: GongshuObservation, *, legacy_flow: LegacyFlow,
            xiezhi_execution: DecisionExecution) -> IntegrationResult:
        if not isinstance(observation, GongshuObservation):
            raise TypeError("observation must be GongshuObservation")
        if not callable(legacy_flow) or not callable(xiezhi_execution):
            raise TypeError("legacy_flow and xiezhi_execution must be callable")
        if not self.config.enabled:
            return IntegrationResult(False, "gongshu_legacy", None, legacy_flow())

        if self._backend is None:
            self._backend = MayflowerXiezhiDecisionBackend(self.config.algorithm)
        decision = self._backend.decide(observation)
        return IntegrationResult(True, "xiezhi", decision, xiezhi_execution(decision))
