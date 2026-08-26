from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from vision2grasp.contracts import Detection2D, RGBFrame
from vision2grasp.geometry import (
    PlanarTableTargetLocalizer,
    create_table_calibration,
    image_to_table,
    load_table_calibration,
    save_table_calibration,
    table_to_image,
)
from vision2grasp.grasp import PlanarTopGraspPlanner
from vision2grasp.visualization import render_real_scene_overlay


def _calibration():
    return create_table_calibration(
        image_width=640,
        image_height=480,
        image_points_px=np.array(
            [[100.0, 80.0], [540.0, 80.0], [540.0, 420.0], [100.0, 420.0]],
            dtype=np.float64,
        ),
        table_width_m=0.44,
        table_height_m=0.34,
    )


def _frame_and_detection() -> tuple[RGBFrame, Detection2D]:
    rgb = np.full((480, 640, 3), 32, dtype=np.uint8)
    mask = np.zeros((480, 640), dtype=np.bool_)
    mask[180:320, 275:365] = True
    frame = RGBFrame(0, 1.0, "synthetic-camera", rgb)
    detection = Detection2D(
        class_id=39,
        class_name="bottle",
        confidence=0.91,
        bbox_xyxy=(275.0, 180.0, 365.0, 320.0),
        mask=mask,
    )
    return frame, detection


class TableCalibrationTests(unittest.TestCase):
    def test_maps_ordered_rectangle_between_pixels_and_measured_xy(self) -> None:
        calibration = _calibration()
        pixels = np.array([[100.0, 80.0], [320.0, 250.0]], dtype=np.float64)
        table = image_to_table(calibration, pixels)
        self.assertTrue(np.allclose(table[0], [0.0, 0.0], atol=1e-8))
        self.assertTrue(np.allclose(table[1], [0.22, 0.17], atol=1e-6))
        self.assertTrue(np.allclose(table_to_image(calibration, table), pixels, atol=1e-6))
        self.assertGreater(calibration.image_coverage_ratio, 0.4)

    def test_rejects_tiny_or_misordered_click_polygon(self) -> None:
        with self.assertRaises(ValueError):
            create_table_calibration(
                image_width=640,
                image_height=480,
                image_points_px=np.array(
                    [[100, 100], [500, 400], [500, 100], [100, 400]], dtype=np.float64
                ),
                table_width_m=0.4,
                table_height_m=0.3,
            )

    def test_calibration_round_trip_preserves_measured_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "calibration.json"
            save_table_calibration(_calibration(), path)
            loaded = load_table_calibration(path)
            self.assertEqual((loaded.image_width, loaded.image_height), (640, 480))
            self.assertTrue(np.allclose(loaded.image_points_px, _calibration().image_points_px))


class RealSceneGeometryTests(unittest.TestCase):
    def test_localizes_bottle_and_generates_three_repeatable_candidates(self) -> None:
        frame, detection = _frame_and_detection()
        target = PlanarTableTargetLocalizer().localize(frame, detection, _calibration())
        self.assertTrue(np.allclose(target.center_table_m, [0.2195, 0.1695], atol=0.002))
        candidates = PlanarTopGraspPlanner().plan(target)
        repeated = PlanarTopGraspPlanner().plan(target)
        self.assertEqual(len(candidates), 3)
        self.assertEqual(
            [candidate.candidate_id for candidate in candidates],
            [candidate.candidate_id for candidate in repeated],
        )
        self.assertTrue(all(candidate.vision_score == detection.confidence for candidate in candidates))
        self.assertTrue(all(np.isfinite(candidate.yaw_rad) for candidate in candidates))

    def test_overlay_draws_mask_table_axes_and_gripper(self) -> None:
        frame, detection = _frame_and_detection()
        calibration = _calibration()
        target = PlanarTableTargetLocalizer().localize(frame, detection, calibration)
        candidates = PlanarTopGraspPlanner().plan(target)
        overlay = render_real_scene_overlay(
            frame,
            calibration=calibration,
            detection=detection,
            target=target,
            candidates=candidates,
        )
        self.assertEqual(overlay.shape, frame.rgb.shape)
        self.assertEqual(overlay.dtype, np.uint8)
        self.assertGreater(int(np.count_nonzero(overlay != frame.rgb)), 1000)


if __name__ == "__main__":
    unittest.main()
