from __future__ import annotations

import unittest

import numpy as np

from vision2grasp.simulation import RobosuiteRGBDSimulator


class RobosuiteIntegrationTests(unittest.TestCase):
    def test_lift_environment_produces_calibrated_rgbd_and_steps(self) -> None:
        simulator = RobosuiteRGBDSimulator()
        try:
            initial = simulator.reset(seed=7)
            initial_robot = simulator.robot_state()
            action = np.zeros(7, dtype=np.float64)
            action[2] = 0.10
            action[-1] = -1.0
            after_action = simulator.apply_action(action)
            after_robot = simulator.robot_state()

            self.assertEqual(initial.rgb.shape, (480, 640, 3))
            self.assertEqual(initial.rgb.dtype, np.uint8)
            self.assertEqual(initial.depth_m.shape, (480, 640))
            self.assertEqual(initial.depth_m.dtype, np.float32)
            self.assertTrue(np.all(np.isfinite(initial.depth_m)))
            self.assertTrue(np.all(initial.depth_m > 0.0))
            self.assertGreater(initial.intrinsics.fx, 0.0)
            self.assertGreater(initial.intrinsics.fy, 0.0)
            self.assertEqual(initial.world_from_camera.shape, (4, 4))
            np.testing.assert_allclose(initial.world_from_camera[3], [0, 0, 0, 1])
            np.testing.assert_allclose(
                initial.world_from_camera[:3, :3].T
                @ initial.world_from_camera[:3, :3],
                np.eye(3),
                atol=1e-7,
            )
            self.assertEqual(after_action.frame_id, initial.frame_id + 1)
            self.assertGreater(after_action.timestamp_s, initial.timestamp_s)
            self.assertEqual(simulator.action_dimension, 7)
            self.assertEqual(initial_robot.world_from_eef.shape, (4, 4))
            np.testing.assert_allclose(
                initial_robot.world_from_eef[:3, :3].T
                @ initial_robot.world_from_eef[:3, :3],
                np.eye(3),
                atol=1e-7,
            )
            self.assertEqual(initial_robot.gripper_qpos.shape, (2,))
            self.assertGreater(after_robot.timestamp_s, initial_robot.timestamp_s)
        finally:
            simulator.close()
            simulator.close()


if __name__ == "__main__":
    unittest.main()
