from __future__ import annotations

from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from vision2grasp.contracts import Detection2D, RGBFrame
from vision2grasp.real_scene import RealScenePerceptionPipeline
from vision2grasp.real_scene_service import RealSceneProcessor
from vision2grasp.sources import RGBArraySource


class _BottleSegmenter:
    model_name = "fake-bottle"

    def predict(self, frame: RGBFrame) -> tuple[Detection2D, ...]:
        height, width = frame.rgb.shape[:2]
        mask = np.zeros((height, width), dtype=np.bool_)
        mask[70:170, 130:190] = True
        return (
            Detection2D(
                39,
                "bottle",
                0.9,
                (130.0, 70.0, 190.0, 170.0),
                mask,
            ),
        )


class RealSceneProcessorTests(unittest.TestCase):
    def test_processes_live_source_then_applies_manual_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            processor = RealSceneProcessor(
                RealScenePerceptionPipeline(_BottleSegmenter()),
                calibration_path=Path(temporary_directory) / "calibration.json",
                target_fps=10.0,
            )
            processor.start()
            processor.set_source(
                RGBArraySource(np.full((240, 320, 3), 80, dtype=np.uint8)),
                kind="image",
            )
            try:
                self._wait_until(lambda: processor.snapshot().get("revision", 0) > 0)
                before = processor.snapshot()
                self.assertEqual(before["phase"], "DETECT")
                self.assertFalse(before["calibration"]["ready"])
                self.assertIsNotNone(processor.image("live"))

                processor.set_calibration(
                    image_points_px=[[20, 20], [300, 20], [300, 220], [20, 220]],
                    table_width_m=0.42,
                    table_height_m=0.30,
                )
                prior_revision = int(before["revision"])
                self._wait_until(
                    lambda: (
                        int(processor.snapshot().get("revision", 0)) > prior_revision
                        and processor.snapshot().get("phase") == "READY"
                    )
                )
                after = processor.snapshot()
                self.assertTrue(after["calibration"]["ready"])
                self.assertEqual(len(after["candidates"]), 3)
                self.assertEqual(after["target"]["provenance"]["center_table_xy"], "measured_calibration")
                self.assertIsNotNone(processor.image("spatial"))
                self.assertIsNotNone(processor.image("grasp"))
            finally:
                processor.stop()

    def _wait_until(self, predicate, timeout_s: float = 3.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.03)
        self.fail("timed out waiting for real-scene processor state")


if __name__ == "__main__":
    unittest.main()
