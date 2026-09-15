"""Optional Gongshu-to-Xiezhi decision adapter."""

from .adapter import GongshuXiezhiAdapter
from .backend import MayflowerXiezhiDecisionBackend, XiezhiUnavailableError
from .contracts import (
    GongshuDecision,
    GongshuObservation,
    IntegrationResult,
    XiezhiAdapterConfig,
    XiezhiDecisionBackend,
)

__all__ = [
    "GongshuDecision",
    "GongshuObservation",
    "GongshuXiezhiAdapter",
    "IntegrationResult",
    "MayflowerXiezhiDecisionBackend",
    "XiezhiAdapterConfig",
    "XiezhiDecisionBackend",
    "XiezhiUnavailableError",
]
