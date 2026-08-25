from __future__ import annotations

import unittest

import numpy as np

from vision2grasp import Detection2D
from vision2grasp.geometry import MaskDepthTargetLocalizer
from vision2grasp.grasp import PCATopGraspPlanner
from vision2grasp.simulation import RobosuiteRGBDSimulator


class GraspPlanningIntegrationTests(unittest.TestCase):
    def test_plans_width_feasible_pose_from_real_rgbd_geometry(self) -> None:
        simulator = RobosuiteRGBDSimulator()
        try:
            frame = simulator.reset(seed=7)
            height, width = frame.depth_m.shape
            half_size = 15
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
                confidence=0.9,
                bbox_xyxy=(
                    float(center_x - half_size),
                    float(center_y - half_size),
                    float(center_x + half_size),
                    float(center_y + half_size),
                ),
                mask=mask,
            )
            target = MaskDepthTargetLocalizer().localize(frame, detection)

            candidate = PCATopGraspPlanner().plan(target)[0]

            rotation = candidate.world_from_grasp[:3, :3]
            np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-7)
            self.assertAlmostEqual(float(np.linalg.det(rotation)), 1.0, places=7)
            np.testing.assert_allclose(rotation[:, 2], [0.0, 0.0, -1.0])
            self.assertTrue(candidate.reachable)
            self.assertGreater(candidate.score, 0.0)
            self.assertLessEqual(candidate.gripper_width_m, 0.08)
            np.testing.assert_allclose(
                candidate.world_from_grasp[:3, 3], target.centroid_world_m
            )
        finally:
            simulator.close()


if __name__ == "__main__":
    unittest.main()

