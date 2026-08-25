from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import numpy as np

from vision2grasp.contracts import ExecutionPhase, GraspCandidate, PandaProprioception
from vision2grasp.control import PandaOSCExecutorConfig, PandaOSCGraspExecutor


class FakePandaBackend:
    action_dimension = 7

    def __init__(self, *, frozen: bool = False) -> None:
        self.pose = np.eye(4, dtype=np.float64)
        self.pose[:3, :3] = np.diag([1.0, -1.0, -1.0])
        self.pose[:3, 3] = [0.0, 0.0, 1.0]
        self.gripper_qpos = np.array([0.02, -0.02], dtype=np.float64)
        self.timestamp_s = 0.0
        self.frozen = frozen
        self.actions: list[np.ndarray] = []
        self.positions: list[np.ndarray] = [self.pose[:3, 3].copy()]

    def robot_state(self) -> PandaProprioception:
        return PandaProprioception(
            timestamp_s=self.timestamp_s,
            world_from_eef=self.pose.copy(),
            gripper_qpos=self.gripper_qpos.copy(),
        )

    def apply_action(self, action: np.ndarray) -> None:
        self.actions.append(action.copy())
        self.timestamp_s += 0.05
        if not self.frozen:
            self.pose[:3, 3] += action[:3] * 0.05
            self.pose[:3, :3] = (
                _rotation_matrix(action[3:6] * 0.50) @ self.pose[:3, :3]
            )
            opening = float(
                np.clip(self.gripper_qpos[0] - action[6] * 0.01, 0.0, 0.04)
            )
            self.gripper_qpos[:] = [opening, -opening]
        self.positions.append(self.pose[:3, 3].copy())


def _rotation_matrix(rotation_vector: np.ndarray) -> np.ndarray:
    angle = float(np.linalg.norm(rotation_vector))
    if angle <= 1e-12:
        return np.eye(3)
    x, y, z = rotation_vector / angle
    skew = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + np.sin(angle) * skew + (1.0 - np.cos(angle)) * (skew @ skew)


def _candidate(**changes: object) -> GraspCandidate:
    pose = np.eye(4, dtype=np.float64)
    angle = 0.4
    world_from_unrotated = np.array(
        [
            [np.cos(angle), -np.sin(angle), 0.0],
            [np.sin(angle), np.cos(angle), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    pose[:3, :3] = world_from_unrotated @ np.diag([1.0, -1.0, -1.0])
    pose[:3, 3] = [0.0, 0.0, 0.88]
    values: dict[str, object] = {
        "candidate_id": "top-pca-test",
        "world_from_grasp": pose,
        "gripper_width_m": 0.04,
        "score": 0.8,
        "reachable": True,
    }
    values.update(changes)
    return GraspCandidate(**values)  # type: ignore[arg-type]


class PandaOSCExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = PandaOSCExecutorConfig(
            home_open_steps=2,
            close_steps=3,
            pregrasp_max_steps=20,
            descend_max_steps=20,
            lift_max_steps=20,
            return_home_max_steps=20,
        )

    def test_executes_all_phases_with_bounded_actions_and_returns_home(self) -> None:
        backend = FakePandaBackend()

        result = PandaOSCGraspExecutor(backend, self.config).execute(_candidate())

        self.assertTrue(result.success, result.message)
        self.assertEqual(
            result.visited_phases,
            (
                ExecutionPhase.HOME,
                ExecutionPhase.PREGRASP,
                ExecutionPhase.DESCEND,
                ExecutionPhase.CLOSE,
                ExecutionPhase.LIFT,
                ExecutionPhase.RETURN_HOME,
                ExecutionPhase.SUCCEEDED,
            ),
        )
        self.assertIn("not evaluated", result.message)
        actions = np.asarray(backend.actions)
        self.assertTrue(np.all(np.abs(actions) <= 1.0))
        self.assertLessEqual(
            float(np.max(np.linalg.norm(actions[:, :3] * 0.05, axis=1))),
            self.config.maximum_translation_step_m + 1e-12,
        )
        self.assertLessEqual(
            float(np.max(np.linalg.norm(actions[:, 3:6] * 0.50, axis=1))),
            self.config.maximum_rotation_step_rad + 1e-12,
        )
        self.assertTrue(np.any(actions[:, 6] < 0.0))
        self.assertTrue(np.any(actions[:, 6] > 0.0))
        self.assertGreater(float(np.max(np.linalg.norm(actions[:, 3:6], axis=1))), 0.0)
        np.testing.assert_allclose(backend.pose[:3, 3], [0.0, 0.0, 1.0], atol=0.008)
        self.assertLess(float(np.min(np.asarray(backend.positions)[:, 2])), 0.90)

    def test_timeout_returns_failed_with_current_phase(self) -> None:
        backend = FakePandaBackend(frozen=True)
        config = PandaOSCExecutorConfig(
            home_open_steps=1,
            close_steps=1,
            pregrasp_max_steps=2,
            descend_max_steps=2,
            lift_max_steps=2,
            return_home_max_steps=2,
        )

        result = PandaOSCGraspExecutor(backend, config).execute(_candidate())

        self.assertFalse(result.success)
        self.assertEqual(
            result.visited_phases,
            (ExecutionPhase.HOME, ExecutionPhase.PREGRASP, ExecutionPhase.FAILED),
        )
        self.assertIn("2-step", result.message)

    def test_rejects_unsafe_candidates_before_motion(self) -> None:
        upward_pose = np.eye(4, dtype=np.float64)
        upward_pose[:3, 3] = [0.0, 0.0, 0.88]
        outside_pose = np.diag([1.0, -1.0, -1.0, 1.0])
        outside_pose[:3, 3] = [0.7, 0.0, 0.88]
        cases = (
            _candidate(reachable=False),
            _candidate(gripper_width_m=0.081),
            _candidate(world_from_grasp=upward_pose),
            _candidate(world_from_grasp=outside_pose),
        )
        for index, candidate in enumerate(cases):
            with self.subTest(case=index):
                backend = FakePandaBackend()
                result = PandaOSCGraspExecutor(backend, self.config).execute(candidate)
                self.assertFalse(result.success)
                self.assertEqual(
                    result.visited_phases,
                    (ExecutionPhase.HOME, ExecutionPhase.FAILED),
                )
                self.assertEqual(backend.actions, [])


class PandaOSCExecutorConfigTests(unittest.TestCase):
    def test_default_toml_freezes_control_settings(self) -> None:
        path = Path(__file__).parents[1] / "configs" / "default.toml"
        with path.open("rb") as stream:
            control = tomllib.load(stream)["control"]

        config = PandaOSCExecutorConfig()
        self.assertEqual(control["backend"], "panda_osc_pose")
        self.assertFalse(control["use_simulation_truth"])
        self.assertEqual(control["workspace_min_m"], list(config.workspace_min_m))
        self.assertEqual(control["workspace_max_m"], list(config.workspace_max_m))
        self.assertEqual(
            control["maximum_translation_step_m"],
            config.maximum_translation_step_m,
        )
        self.assertEqual(control["return_home_max_steps"], config.return_home_max_steps)

    def test_rejects_invalid_safety_limits(self) -> None:
        with self.assertRaisesRegex(ValueError, "workspace"):
            PandaOSCExecutorConfig(workspace_min_m=(1.0, 0.0, 0.0))
        with self.assertRaisesRegex(ValueError, "output scale"):
            PandaOSCExecutorConfig(maximum_translation_step_m=0.06)
        with self.assertRaisesRegex(ValueError, "positive"):
            PandaOSCExecutorConfig(close_steps=0)


if __name__ == "__main__":
    unittest.main()
