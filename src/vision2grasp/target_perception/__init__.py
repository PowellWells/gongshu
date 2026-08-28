"""Object-agnostic target perception for manual target selection."""

from .contracts import UNKNOWN_TARGET_LABEL, TargetInstance
from .fastsam_adapter import FastSAMTargetSegmenter, FastSAMTargetSegmenterConfig
from .interfaces import TargetInstanceSegmenter
from .service import TARGET_PERCEPTION_SCHEMA_VERSION, TargetPerceptionService

__all__ = [
    "FastSAMTargetSegmenter",
    "FastSAMTargetSegmenterConfig",
    "TARGET_PERCEPTION_SCHEMA_VERSION",
    "TargetInstance",
    "TargetInstanceSegmenter",
    "TargetPerceptionService",
    "UNKNOWN_TARGET_LABEL",
]
