from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from vision2grasp.simulation import (
    RobosuiteRGBDSimulator,
    RobosuiteSimulationConfig,
)


class FakeEnvironment:
    action_dim = 7

    def __init__(self, width: int = 4, height: int = 3) -> None:
        self.width = width
        self.height = height
        self.sim = SimpleNamespace(data=SimpleNamespace(time=0.0))
        self.close_calls = 0
        self.reset_calls = 0
        self.actions: list[np.ndarray] = []

    def observation(self) -> dict[str, np.ndarray]:
        return {
            "agentview_image": np.zeros(
                (self.height, self.width, 3), dtype=np.uint8
            ),
            "agentview_depth": np.full(
                (self.height, self.width, 1), 0.25, dtype=np.float32
            ),
        }

    def reset(self) -> dict[str, np.ndarray]:
        self.reset_calls += 1
        self.sim.data.time = 0.0
        return self.observation()

    def step(
        self, action: np.ndarray
    ) -> tuple[dict[str, np.ndarray], float, bool, dict[str, object]]:
        self.actions.append(action.copy())
        self.sim.data.time += 0.05
        return self.observation(), 0.0, False, {}

    def close(self) -> None:
        self.close_calls += 1


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = RobosuiteSimulationConfig(camera_width=4, camera_height=3)
        self.environments: list[FakeEnvironment] = []
        self.seeds: list[int | None] = []

        def factory(
            config: RobosuiteSimulationConfig, seed: int | None
        ) -> FakeEnvironment:
            self.assertEqual(config, self.config)
            environment = FakeEnvironment(
                width=config.camera_width, height=config.camera_height
            )
            self.environments.append(environment)
            self.seeds.append(seed)
            return environment

        self.patches = (
            patch(
                "vision2grasp.simulation.robosuite_adapter._make_robosuite_environment",
                side_effect=factory,
            ),
            patch(
                "vision2grasp.simulation.robosuite_adapter._metric_depth",
                side_effect=lambda _sim, depth: np.asarray(depth) + 0.5,
            ),
            patch(
                "vision2grasp.simulation.robosuite_adapter._camera_intrinsic_matrix",
                return_value=np.array(
                    [[100.0, 0.0, 2.0], [0.0, 101.0, 1.5], [0.0, 0.0, 1.0]]
                ),
            ),
            patch(
                "vision2grasp.simulation.robosuite_adapter._world_from_camera_matrix",
                return_value=np.eye(4),
            ),
        )
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self) -> None:
        for active_patch in reversed(self.patches):
            active_patch.stop()

    def test_reset_and_capture_return_valid_independent_frames(self) -> None:
        simulator = RobosuiteRGBDSimulator(self.config)

        reset_frame = simulator.reset()
        capture_frame = simulator.capture()

        self.assertEqual(self.seeds, [7])
        self.assertEqual(reset_frame.frame_id, 0)
        self.assertEqual(capture_frame.frame_id, 1)
        self.assertEqual(reset_frame.rgb.shape, (3, 4, 3))
        self.assertEqual(reset_frame.rgb.dtype, np.uint8)
        self.assertEqual(reset_frame.depth_m.dtype, np.float32)
        np.testing.assert_allclose(reset_frame.depth_m, 0.75)
        self.assertEqual(reset_frame.intrinsics.fx, 100.0)
        self.assertEqual(reset_frame.intrinsics.fy, 101.0)
        np.testing.assert_array_equal(reset_frame.world_from_camera, np.eye(4))

        self.environments[0].observation()["agentview_image"].fill(255)
        self.assertTrue(np.all(reset_frame.rgb == 0))

    def test_apply_action_validates_and_forwards_a_copy(self) -> None:
        simulator = RobosuiteRGBDSimulator(self.config)
        simulator.reset()
        action = np.arange(7, dtype=np.float64)

        frame = simulator.apply_action(action)
        action.fill(-1.0)

        self.assertEqual(frame.frame_id, 1)
        self.assertAlmostEqual(frame.timestamp_s, 0.05)
        np.testing.assert_array_equal(
            self.environments[0].actions[0], np.arange(7, dtype=np.float64)
        )
        with self.assertRaisesRegex(ValueError, "shape"):
            simulator.apply_action(np.zeros(6, dtype=np.float64))
        with self.assertRaisesRegex(ValueError, "finite"):
            simulator.apply_action(
                np.array([0.0, 0.0, np.nan, 0.0, 0.0, 0.0, 0.0])
            )

    def test_explicit_seed_recreates_environment(self) -> None:
        simulator = RobosuiteRGBDSimulator(self.config)
        simulator.reset()
        first_environment = self.environments[0]

        simulator.reset(seed=19)

        self.assertEqual(self.seeds, [7, 19])
        self.assertEqual(first_environment.close_calls, 1)
        self.assertEqual(len(self.environments), 2)

    def test_close_is_idempotent_and_prevents_reuse(self) -> None:
        simulator = RobosuiteRGBDSimulator(self.config)
        with self.assertRaisesRegex(RuntimeError, "reset"):
            simulator.capture()
        simulator.reset()

        simulator.close()
        simulator.close()

        self.assertEqual(self.environments[0].close_calls, 1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            simulator.reset()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            simulator.capture()

    def test_missing_rgbd_observation_is_rejected(self) -> None:
        simulator = RobosuiteRGBDSimulator(self.config)
        environment = FakeEnvironment(width=4, height=3)
        environment.observation = lambda: {  # type: ignore[method-assign]
            "agentview_image": np.zeros((3, 4, 3), dtype=np.uint8)
        }
        self.environments.clear()

        with patch(
            "vision2grasp.simulation.robosuite_adapter._make_robosuite_environment",
            return_value=environment,
        ):
            with self.assertRaisesRegex(KeyError, "agentview_depth"):
                simulator.reset()


class SimulationConfigTests(unittest.TestCase):
    def test_rejects_invalid_dimensions(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimensions"):
            RobosuiteSimulationConfig(camera_width=0)


if __name__ == "__main__":
    unittest.main()

