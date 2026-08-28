from __future__ import annotations

import unittest

import numpy as np

from vision2grasp import Detection2D
from vision2grasp.geometry import MaskDepthTargetLocalizer
from vision2grasp.simulation import RobosuiteRGBDSimulator


class GeometryIntegrationTests(unittest.TestCase):
    def test_localizes_center_region_from_real_robosuite_rgbd_frame(self) -> None:
        simulator = RobosuiteRGBDSimulator()
        try:
            frame = simulator.reset(seed=7)
            height, width = frame.depth_m.shape
            half_size = 40
            center_x = width // 2
            center_y = height // 2
            mask = np.zeros((height, width), dtype=np.bool_)
            mask[
                center_y - half_size : center_y + half_size,
                center_x - half_size : center_x + half_size,
            ] = True
            detection = Detection2D(
                class_id=39,
                class_name="bottle-roi",
                confidence=1.0,
                bbox_xyxy=(
                    float(center_x - half_size),
                    float(center_y - half_size),
                    float(center_x + half_size),
                    float(center_y + half_size),
                ),
                mask=mask,
            )

            target = MaskDepthTargetLocalizer().localize(frame, detection)

            self.assertEqual(target.detection, detection)
            self.assertGreaterEqual(target.depth_valid_ratio, 0.99)
            self.assertGreaterEqual(target.points_world_m.shape[0], 30)
            self.assertLessEqual(target.points_world_m.shape[0], 4096)
            self.assertTrue(np.all(np.isfinite(target.points_world_m)))
            self.assertTrue(np.all(np.isfinite(target.centroid_world_m)))
            self.assertGreater(float(np.linalg.norm(target.centroid_world_m)), 0.0)
        finally:
            simulator.close()


if __name__ == "__main__":
    unittest.main()
