from __future__ import annotations

import hashlib
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen

import numpy as np

from vision2grasp.experiment_lab import build_behavior_comparison
from vision2grasp.simulation import SimulationRecording
from vision2grasp.simulation.recording import save_recording
from vision2grasp.simulation.validation_contracts import (
    SimulationState,
    ValidationResult,
)
from run_vision2grasp_app import AppRequestHandler


def make_behavior_recording(
    *,
    recording_id: str,
    provider_id: str,
    algorithm_id: str,
    algorithm_name: str,
    candidate_id: str,
    endpoint_x: float,
) -> SimulationRecording:
    timestamps = np.array([0.0, 0.5, 1.0], dtype=np.float64)
    eef_positions = np.array(
        [
            [0.40, 0.00, 0.80],
            [0.40 + (endpoint_x - 0.40) / 2.0, 0.00, 0.88],
            [endpoint_x, 0.00, 0.82],
        ],
        dtype=np.float64,
    )
    model_xml = "<mujoco model='behavior-test'><worldbody/></mujoco>"
    result = ValidationResult(
        state=SimulationState.SUCCESS,
        reason=None,
        state_machine_complete=True,
        invalid_table_collision=False,
        gripper_close_executed=True,
        lift_height_m=0.08,
        stable_window_passed=True,
    )
    return SimulationRecording(
        recording_id=recording_id,
        run_id=recording_id.replace("rec-", "run-"),
        created_at="2026-09-17T12:00:00+08:00",
        sample_hz=2.0,
        timestamps=timestamps,
        qpos=np.zeros((3, 2), dtype=np.float64),
        qvel=np.zeros((3, 2), dtype=np.float64),
        gripper_states=np.zeros((3, 2), dtype=np.float64),
        target_poses=np.zeros((3, 7), dtype=np.float64),
        target_velocities=np.zeros((3, 6), dtype=np.float64),
        eef_positions=eef_positions,
        collision_states=np.zeros(3, dtype=np.bool_),
        lift_heights=np.array([0.0, 0.02, 0.08], dtype=np.float64),
        validation_states=("APPROACH", "GRASP", "SUCCESS"),
        contacts=((), (), ()),
        events=(),
        result=result,
        request_metadata={
            "simulation_attempt": {
                "snapshot_id": "snapshot-42",
                "target_id": "target-42-01",
                "candidate_id": candidate_id,
            },
            "scene_transform": {
                "grasp_position_world": [endpoint_x, 0.0, 0.82],
            },
            "decision_context": {
                "provider": provider_id,
                "algorithm_id": algorithm_id,
                "algorithm_name": algorithm_name,
                "algorithm_version": "v0.1",
                "decision_id": f"decision-{candidate_id.lower()}",
                "selected_candidate_id": candidate_id,
            },
        },
        compatibility={
            "mujoco_version": "test",
            "model_sha256": hashlib.sha256(model_xml.encode("utf-8")).hexdigest(),
            "nq": 2,
            "nv": 2,
        },
        model_xml=model_xml,
    )


class BehaviorComparisonFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.xiezhi = make_behavior_recording(
            recording_id="rec-xiezhi",
            provider_id="xiezhi",
            algorithm_id="xiezhi_decision_v0_1",
            algorithm_name="Xiezhi Decision",
            candidate_id="C1",
            endpoint_x=0.44,
        )
        self.external = make_behavior_recording(
            recording_id="rec-external",
            provider_id="external_baseline",
            algorithm_id="mock_external_baseline_v0_1",
            algorithm_name="Mock External Baseline",
            candidate_id="C3",
            endpoint_x=0.50,
        )

    def test_runtime_recording_projects_real_trajectory_into_behavior_record(self) -> None:
        behavior = self.xiezhi.behavior_record()

        self.assertIsNotNone(behavior)
        assert behavior is not None
        self.assertEqual(behavior.algorithm_id, "xiezhi_decision_v0_1")
        self.assertEqual(behavior.selected_candidate_id, "C1")
        self.assertEqual(len(behavior.trajectory_points), 3)
        self.assertEqual(behavior.trajectory_points[-1].position_world, (0.44, 0.0, 0.82))
        self.assertEqual(behavior.execution_time, 1.0)

    def test_same_scene_algorithms_create_different_behavior_records(self) -> None:
        records = (
            self.xiezhi.behavior_record(),
            self.external.behavior_record(),
        )
        comparison = build_behavior_comparison(
            record for record in records if record is not None
        )

        self.assertEqual(comparison["status"], "READY")
        self.assertEqual(comparison["scene_id"], "snapshot-42")
        self.assertEqual(comparison["left"]["selected_candidate_id"], "C1")
        self.assertEqual(comparison["right"]["selected_candidate_id"], "C3")
        self.assertTrue(
            comparison["trajectory_difference"]["selected_candidate_changed"]
        )
        self.assertGreater(
            comparison["trajectory_difference"]["endpoint_distance_m"],
            0.0,
        )

    def test_behavior_trajectory_is_saved_with_simulation_recording(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            saved = save_recording(self.external, Path(temporary))
            behavior_path = Path(saved.saved_path) / "behavior_record.json"
            payload = json.loads(behavior_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "gongshu.behavior-record/v1")
        self.assertEqual(payload["storage"], "SAVED")
        self.assertEqual(payload["selected_candidate_id"], "C3")
        self.assertEqual(len(payload["trajectory_points"]), 3)

    def test_comparison_page_api_returns_two_behavior_records(self) -> None:
        records = tuple(
            record
            for record in (
                self.xiezhi.behavior_record(),
                self.external.behavior_record(),
            )
            if record is not None
        )

        class App:
            @staticmethod
            def behavior_comparison():
                return build_behavior_comparison(records)

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(AppRequestHandler, app=App()),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/api/behavior-comparison",
                timeout=2,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["left"]["algorithm_id"], "xiezhi_decision_v0_1")
        self.assertEqual(
            payload["right"]["algorithm_id"],
            "mock_external_baseline_v0_1",
        )


if __name__ == "__main__":
    unittest.main()
