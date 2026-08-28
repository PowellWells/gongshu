"""OpenCV-backed real camera, network stream, and image-file sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import time
from typing import Protocol

import cv2
import numpy as np

from vision2grasp.contracts import RGBFrame


@dataclass(frozen=True, slots=True)
class OpenCVCameraConfig:
    """Stable capture settings for a local camera index or network URL."""

    source: int | str = 0
    width: int = 640
    height: int = 480
    camera_name: str = "real-camera"

    def __post_init__(self) -> None:
        if isinstance(self.source, int) and self.source < 0:
            raise ValueError("camera index must be non-negative")
        if isinstance(self.source, str) and not self.source.strip():
            raise ValueError("camera URL must not be empty")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("camera dimensions must be positive")
        if not self.camera_name.strip():
            raise ValueError("camera_name must not be empty")


class _VideoCapture(Protocol):
    def isOpened(self) -> bool: ...

    def read(self) -> tuple[bool, np.ndarray]: ...

    def set(self, prop_id: int, value: float) -> bool: ...

    def release(self) -> None: ...


def _open_video_capture(source: int | str) -> _VideoCapture:
    if os.name == "nt" and isinstance(source, int):
        return cv2.VideoCapture(source, cv2.CAP_DSHOW)
    return cv2.VideoCapture(source)


class OpenCVCameraSource:
    """Read RGB frames from a Windows webcam or OpenCV-compatible URL."""

    def __init__(self, config: OpenCVCameraConfig | None = None) -> None:
        self._config = config or OpenCVCameraConfig()
        self._capture = _open_video_capture(self._config.source)
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(self._config.width))
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self._config.height))
        if not self._capture.isOpened():
            self._capture.release()
            raise RuntimeError(f"unable to open camera source {self._config.source!r}")
        self._next_frame_id = 0
        self._closed = False

    @property
    def source_name(self) -> str:
        return self._config.camera_name

    def capture(self) -> RGBFrame:
        if self._closed:
            raise RuntimeError("camera source is closed")
        ok, bgr = self._capture.read()
        if not ok or bgr is None:
            raise RuntimeError("camera source did not return a frame")
        if bgr.ndim != 3 or bgr.shape[2] != 3 or bgr.dtype != np.uint8:
            raise ValueError("camera frame must be an HxWx3 uint8 BGR image")
        frame = RGBFrame(
            frame_id=self._next_frame_id,
            timestamp_s=time.monotonic(),
            camera_name=self._config.camera_name,
            rgb=np.ascontiguousarray(bgr[..., ::-1]),
        )
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        if self._closed:
            return
        self._capture.release()
        self._closed = True


class ImageFileSource:
    """Expose a local RGB image through the same frame-source contract."""

    def __init__(self, path: Path, *, camera_name: str = "image-file") -> None:
        self._path = Path(path)
        if not camera_name.strip():
            raise ValueError("camera_name must not be empty")
        bgr = cv2.imread(str(self._path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise FileNotFoundError(f"unable to read image file: {self._path}")
        self._rgb = np.ascontiguousarray(bgr[..., ::-1])
        self._camera_name = camera_name
        self._next_frame_id = 0
        self._closed = False

    @property
    def source_name(self) -> str:
        return self._camera_name

    def capture(self) -> RGBFrame:
        if self._closed:
            raise RuntimeError("image source is closed")
        frame = RGBFrame(
            frame_id=self._next_frame_id,
            timestamp_s=time.monotonic(),
            camera_name=self._camera_name,
            rgb=self._rgb.copy(),
        )
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        self._closed = True


class RGBArraySource:
    """Repeat one uploaded RGB image without introducing fake depth."""

    def __init__(self, rgb: np.ndarray, *, camera_name: str = "uploaded-image") -> None:
        array = np.asarray(rgb)
        if array.ndim != 3 or array.shape[2] != 3 or array.dtype != np.uint8:
            raise ValueError("uploaded RGB image must have shape (H, W, 3) and uint8 dtype")
        if not camera_name.strip():
            raise ValueError("camera_name must not be empty")
        self._rgb = np.ascontiguousarray(array).copy()
        self._camera_name = camera_name
        self._next_frame_id = 0
        self._closed = False

    @property
    def source_name(self) -> str:
        return self._camera_name

    def capture(self) -> RGBFrame:
        if self._closed:
            raise RuntimeError("image source is closed")
        frame = RGBFrame(
            frame_id=self._next_frame_id,
            timestamp_s=time.monotonic(),
            camera_name=self._camera_name,
            rgb=self._rgb.copy(),
        )
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        self._closed = True


__all__ = [
    "ImageFileSource",
    "OpenCVCameraConfig",
    "OpenCVCameraSource",
    "RGBArraySource",
]
