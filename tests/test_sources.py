from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from vision2grasp.contracts import RGBFrame
from vision2grasp.sources import (
    ImageFileSource,
    OpenCVCameraConfig,
    OpenCVCameraSource,
)


class _FakeCapture:
    def __init__(self, frames: list[np.ndarray], *, opened: bool = True) -> None:
        self.frames = frames
        self.opened = opened
        self.released = False
        self.settings: list[tuple[int, float]] = []

    def isOpened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def set(self, prop_id: int, value: float) -> bool:
        self.settings.append((prop_id, value))
        return True

    def release(self) -> None:
        self.released = True


class RGBFrameTests(unittest.TestCase):
    def test_rgb_frame_rejects_fake_depth_and_invalid_rgb(self) -> None:
        with self.assertRaises(ValueError):
            RGBFrame(0, 0.0, "camera", np.zeros((10, 10), dtype=np.uint8))
        with self.assertRaises(ValueError):
            RGBFrame(0, 0.0, "camera", np.zeros((10, 10, 3), dtype=np.float32))


class CameraSourceTests(unittest.TestCase):
    def test_camera_source_converts_bgr_and_is_close_safe(self) -> None:
        bgr = np.zeros((3, 4, 3), dtype=np.uint8)
        bgr[0, 0] = [10, 20, 30]
        fake = _FakeCapture([bgr])
        with patch(
            "vision2grasp.sources.opencv_sources._open_video_capture",
            return_value=fake,
        ):
            source = OpenCVCameraSource(OpenCVCameraConfig(source=0))
            frame = source.capture()
            self.assertEqual(frame.rgb[0, 0].tolist(), [30, 20, 10])
            self.assertEqual(frame.frame_id, 0)
            self.assertEqual(source.source_name, "real-camera")
            source.close()
            source.close()
            self.assertTrue(fake.released)
            with self.assertRaises(RuntimeError):
                source.capture()

    def test_camera_source_rejects_unavailable_device(self) -> None:
        fake = _FakeCapture([], opened=False)
        with patch(
            "vision2grasp.sources.opencv_sources._open_video_capture",
            return_value=fake,
        ):
            with self.assertRaises(RuntimeError):
                OpenCVCameraSource(OpenCVCameraConfig(source=0))
        self.assertTrue(fake.released)


class ImageFileSourceTests(unittest.TestCase):
    def test_image_file_source_returns_independent_rgb_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "sample.png"
            bgr = np.zeros((5, 7, 3), dtype=np.uint8)
            bgr[:, :] = [4, 5, 6]
            self.assertTrue(cv2.imwrite(str(path), bgr))
            source = ImageFileSource(path)
            first = source.capture()
            second = source.capture()
            self.assertEqual(first.rgb[0, 0].tolist(), [6, 5, 4])
            self.assertEqual((first.frame_id, second.frame_id), (0, 1))
            first.rgb[0, 0] = 0
            self.assertEqual(second.rgb[0, 0].tolist(), [6, 5, 4])
            source.close()


if __name__ == "__main__":
    unittest.main()
