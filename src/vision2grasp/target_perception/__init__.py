"""Object-agnostic target perception for manual target selection."""

from .contracts import (
    UNKNOWN_TARGET_LABEL,
    TargetInstance,
    TargetLockMetadata,
    TargetSceneSnapshot,
)
from .fastsam_adapter import (
    FASTSAM_MODEL_ASSET,
    FastSAMTargetSegmenter,
    FastSAMTargetSegmenterConfig,
)
from .interfaces import TargetInstanceSegmenter
from .model_resolver import (
    FASTSAM_CACHE_ENV,
    FastSAMChecksumError,
    FastSAMDownloadError,
    FastSAMModelError,
    FastSAMModelLoadError,
    FastSAMModelLocation,
    FastSAMModelNotFoundError,
    FastSAMModelResolver,
    ResolvedFastSAMModel,
)
from .service import TARGET_PERCEPTION_SCHEMA_VERSION, TargetPerceptionService

__all__ = [
    "FastSAMTargetSegmenter",
    "FastSAMTargetSegmenterConfig",
    "FASTSAM_MODEL_ASSET",
    "FASTSAM_CACHE_ENV",
    "FastSAMChecksumError",
    "FastSAMDownloadError",
    "FastSAMModelError",
    "FastSAMModelLoadError",
    "FastSAMModelLocation",
    "FastSAMModelNotFoundError",
    "FastSAMModelResolver",
    "ResolvedFastSAMModel",
    "TARGET_PERCEPTION_SCHEMA_VERSION",
    "TargetInstance",
    "TargetLockMetadata",
    "TargetSceneSnapshot",
    "TargetInstanceSegmenter",
    "TargetPerceptionService",
    "UNKNOWN_TARGET_LABEL",
]
