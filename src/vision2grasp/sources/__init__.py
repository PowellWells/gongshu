"""Visual sources shared by simulation and real-scene pipelines."""

from .interfaces import FrameSource, VisionFrame
from .opencv_sources import (
    ImageFileSource,
    OpenCVCameraConfig,
    OpenCVCameraSource,
    RGBArraySource,
)

__all__ = [
    "FrameSource",
    "ImageFileSource",
    "OpenCVCameraConfig",
    "OpenCVCameraSource",
    "RGBArraySource",
    "VisionFrame",
]
