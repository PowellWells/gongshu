"""Object-agnostic target perception for manual target selection."""

from .contracts import UNKNOWN_TARGET_LABEL, TargetInstance, TargetSceneSnapshot
from .fastsam_adapter import (
    FASTSAM_MODEL_ASSET,
    FastSAMTargetSegmenter,
    FastSAMTargetSegmenterConfig,
)
from .interfaces import TargetInstanceSegmenter
from .service import TARGET_PERCEPTION_SCHEMA_VERSION, TargetPerceptionService

__all__ = [
    "FastSAMTargetSegmenter",
    "FastSAMTargetSegmenterConfig",
    "FASTSAM_MODEL_ASSET",
    "TARGET_PERCEPTION_SCHEMA_VERSION",
    "TargetInstance",
    "TargetSceneSnapshot",
    "TargetInstanceSegmenter",
    "TargetPerceptionService",
    "UNKNOWN_TARGET_LABEL",
]
