"""Optional Gongshu-to-Xiezhi integration boundaries."""

from .lifecycle import (
    GongshuRuntimeContext,
    GongshuXiezhiLifecycleAdapter,
    LifecycleRuntimePort,
    XiezhiLifecycleStatus,
)

__all__ = [
    "GongshuDecision",
    "GongshuObservation",
    "GongshuXiezhiAdapter",
    "GongshuRuntimeContext",
    "GongshuXiezhiLifecycleAdapter",
    "IntegrationResult",
    "MayflowerXiezhiDecisionBackend",
    "LifecycleRuntimePort",
    "XiezhiAdapterConfig",
    "XiezhiDecisionBackend",
    "XiezhiLifecycleStatus",
    "XiezhiUnavailableError",
]


def __getattr__(name: str):
    """Keep the active lifecycle path independent from dormant decision assets."""
    if name == "GongshuXiezhiAdapter":
        from .adapter import GongshuXiezhiAdapter

        return GongshuXiezhiAdapter
    if name in {"MayflowerXiezhiDecisionBackend", "XiezhiUnavailableError"}:
        from .backend import MayflowerXiezhiDecisionBackend, XiezhiUnavailableError

        return {
            "MayflowerXiezhiDecisionBackend": MayflowerXiezhiDecisionBackend,
            "XiezhiUnavailableError": XiezhiUnavailableError,
        }[name]
    if name in {
        "GongshuDecision",
        "GongshuObservation",
        "IntegrationResult",
        "XiezhiAdapterConfig",
        "XiezhiDecisionBackend",
    }:
        from .contracts import (
            GongshuDecision,
            GongshuObservation,
            IntegrationResult,
            XiezhiAdapterConfig,
            XiezhiDecisionBackend,
        )

        return {
            "GongshuDecision": GongshuDecision,
            "GongshuObservation": GongshuObservation,
            "IntegrationResult": IntegrationResult,
            "XiezhiAdapterConfig": XiezhiAdapterConfig,
            "XiezhiDecisionBackend": XiezhiDecisionBackend,
        }[name]
    raise AttributeError(name)
