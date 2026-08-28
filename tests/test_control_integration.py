from __future__ import annotations

import unittest

import numpy as np

from vision2grasp.contracts import ExecutionPhase, GraspCandidate, PandaProprioception
from vision2grasp.control import PandaOSCExecutorConfig, PandaOSCGraspExecutor
from vision2grasp.simulation import RobosuiteRGBDSimulator, RobosuiteSimulationConfig


class RecordingBackend:
    def __init__(self, simulator: RobosuiteRGBDSimulator) -> None:
        self.simulator = simulator
        self.states: list[PandaProprioception] = [simulator.robot_state()]

    @property
    def action_dimension(self) -> int:
        return self.simulator.action_dimension

    def robot_state(self) -> PandaProprioception:
        return self.simulator.robot_state()

    def apply_action(self, action: np.ndarray) -> object:
        frame = self.simulator.apply_action(action)
        self.states.append(self.simulator.robot_state())
        return frame


class PandaControlIntegrationTests(unittest.TestCase):
    def test_real_lift_runs_all_phases_using_robot_proprioception(self) -> None:
        simulator = RobosuiteRGBDSimulator(
            RobosuiteSimulationConfig(camera_width=64, camera_height=48, horizon=300)
        )
        try:
            simulator.reset(seed=7)
            backend = RecordingBackend(simulator)
            initial = backend.states[0]
            pose = initial.world_from_eef.copy()
            pose[:3, 3] += pose[:3, 2] * 0.02
            candidate = GraspCandidate(
                candidate_id="real-lift-safe-motion",
                world_from_grasp=pose,
                gripper_width_m=0.04,
                score=0.8,
                reachable=True,
            )
            config = PandaOSCExecutorConfig(
                pregrasp_offset_m=0.02,
                lift_offset_m=0.03,
                position_tolerance_m=0.006,
                orientation_tolerance_rad=0.10,
                home_open_steps=6,
                close_steps=10,
                pregrasp_max_steps=30,
                descend_max_steps=50,
                lift_max_steps=50,
                return_home_max_steps=60,
            )

            result = PandaOSCGraspExecutor(backend, config).execute(candidate)

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
            positions = np.asarray(
                [state.world_from_eef[:3, 3] for state in backend.states]
            )
            grippers = np.asarray([state.gripper_qpos for state in backend.states])
            displacement = np.linalg.norm(positions - positions[0], axis=1)
            gripper_displacement = np.linalg.norm(grippers - grippers[0], axis=1)
            self.assertGreater(float(np.max(displacement)), 0.008)
            self.assertGreater(float(np.max(gripper_displacement)), 0.005)
            self.assertLess(
                float(np.linalg.norm(positions[-1] - positions[0])),
                config.position_tolerance_m + 0.003,
            )
        finally:
            simulator.close()


if __name__ == "__main__":
    unittest.main()
