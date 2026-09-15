"""Visual sources shared by simulation and real-scene pipelines."""

from .interfaces import FrameSource, VisionFrame
from .local_image import (
    LOCAL_IMAGE_SCHEMA_VERSION,
    MAX_LOCAL_IMAGE_BYTES,
    OFFLINE_RUN_SCHEMA_VERSION,
    LocalImageAdapter,
    LocalImageObservation,
)
from .opencv_sources import (
    ImageFileSource,
    OpenCVCameraConfig,
    OpenCVCameraSource,
    RGBArraySource,
)

__all__ = [
    "FrameSource",
    "ImageFileSource",
    "LOCAL_IMAGE_SCHEMA_VERSION",
    "LocalImageAdapter",
    "LocalImageObservation",
    "MAX_LOCAL_IMAGE_BYTES",
    "OFFLINE_RUN_SCHEMA_VERSION",
    "OpenCVCameraConfig",
    "OpenCVCameraSource",
    "RGBArraySource",
    "VisionFrame",
]
