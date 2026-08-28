from __future__ import annotations

import unittest

import numpy as np

from vision2grasp.contracts import Detection2D, RGBFrame
from vision2grasp.geometry import create_table_calibration
from vision2grasp.real_scene import (
    RealScenePerceptionPipeline,
    RealScenePhase,
    encode_overlay_jpeg,
)


class _Segmenter:
    model_name = "fake-bottle-segmenter"

    def __init__(self, detections: tuple[Detection2D, ...]) -> None:
        self._detections = detections

    def predict(self, frame: RGBFrame) -> tuple[Detection2D, ...]:
        return self._detections


def _fixture() -> tuple[RGBFrame, Detection2D]:
    rgb = np.full((240, 320, 3), 80, dtype=np.uint8)
    mask = np.zeros((240, 320), dtype=np.bool_)
    mask[85:175, 130:190] = True
    return (
        RGBFrame(0, 1.0, "camera", rgb),
        Detection2D(39, "bottle", 0.88, (130.0, 85.0, 190.0, 175.0), mask),
    )


class RealScenePipelineTests(unittest.TestCase):
    def test_detects_without_inventing_table_coordinates_before_calibration(self) -> None:
        frame, detection = _fixture()
        result = RealScenePerceptionPipeline(_Segmenter((detection,))).process(frame, None)
        self.assertTrue(result.success)
        self.assertEqual(result.phase, RealScenePhase.DETECT)
        self.assertIsNone(result.target)
        self.assertEqual(result.candidates, ())
        self.assertFalse(result.calibrated)

    def test_calibrated_frame_produces_candidates_and_jpeg(self) -> None:
        frame, detection = _fixture()
        calibration = create_table_calibration(
            image_width=320,
            image_height=240,
            image_points_px=np.array(
                [[20, 20], [300, 20], [300, 220], [20, 220]], dtype=np.float64
            ),
            table_width_m=0.42,
            table_height_m=0.30,
        )
        result = RealScenePerceptionPipeline(_Segmenter((detection,))).process(
            frame, calibration
        )
        self.assertTrue(result.success)
        self.assertEqual(result.phase, RealScenePhase.READY)
        self.assertIsNotNone(result.target)
        self.assertEqual(len(result.candidates), 3)
        jpeg = encode_overlay_jpeg(result)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))

    def test_no_bottle_is_reported_without_fake_result(self) -> None:
        frame, _ = _fixture()
        result = RealScenePerceptionPipeline(_Segmenter(())).process(frame, None)
        self.assertFalse(result.success)
        self.assertEqual(result.phase, RealScenePhase.DETECT)
        self.assertIsNone(result.selected_detection)


if __name__ == "__main__":
    unittest.main()
