from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from run_vision2grasp_app import Vision2GraspApp
from vision2grasp.experiment_lab import ExperimentTrialRecorder
from vision2grasp.grasp_planning import CandidateFeasibility, GraspCandidate
from vision2grasp.intelligence import DecisionAction, IntelligenceService
from vision2grasp.sources import LocalImageAdapter


def make_outcome(*, score: float = 0.92, executable: bool = True):
    candidate = GraspCandidate(
        candidate_id="candidate-01",
        grasp_point_xyz=np.array([0.01, -0.02, 0.73]),
        approach_vector=np.array([0.0, 0.0, 1.0]),
        closing_vector=np.array([1.0, 0.0, 0.0]),
        grasp_angle=0.0,
        gripper_width=0.04,
        quality_score=score,
        score_factors={"quality": score},
        ranking_score=score,
        feasibility=(
            CandidateFeasibility.EXECUTABLE
            if executable
            else CandidateFeasibility.REJECTED
        ),
        rejection_reasons=() if executable else ("LOW_GRASP_QUALITY",),
        source_frame_id=42,
        target_instance_id="target-42-01",
    )
    plan = None if not executable else SimpleNamespace(
        target_id="target-42-01",
        snapshot_id="snapshot-42",
        source_frame_id=42,
        best_candidate_id="candidate-01",
        confidence=SimpleNamespace(value=0.90),
    )
    return SimpleNamespace(
        candidates=(candidate,),
        plan=plan,
        planning_time_s=0.02,
        grasp_uncertainty=None,
        spatial_uncertainty=None,
    )


def image_bytes() -> bytes:
    bgr = np.full((8, 12, 3), 80, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("test image encoding failed")
    return encoded.tobytes()


class IntelligenceRuntimeTests(unittest.TestCase):
    def test_xiezhi_rule_based_provider_selects_candidate_through_standard_interface(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)
        decision = service.decide(make_outcome())
        self.assertEqual(decision.provider_id, "xiezhi")
        self.assertEqual(decision.algorithm_id, "rule_based")
        self.assertEqual(decision.selected_action, DecisionAction.EXECUTE_GRASP)
        self.assertEqual(decision.selected_candidate_id, "candidate-01")
        self.assertTrue(decision.authorizes_execution)
        state = service.snapshot()
        self.assertTrue(state["decision_available"])
        self.assertEqual(state["last_decision"]["confidence"], 0.91)
        self.assertEqual(
            state["last_decision"]["diagnostics"]["provider_score_type"],
            "MEAN_PLANNER_RANKING_AND_EVIDENCE_CONFIDENCE",
        )
        self.assertIn(
            {"provider": "xiezhi", "algorithm": "rule_based"},
            state["available_algorithms"],
        )

    def test_xiezhi_load_failure_falls_back_to_gongshu_baseline(self) -> None:
        with patch(
            "vision2grasp.intelligence.registry.XiezhiDecisionProvider",
            side_effect=RuntimeError("runtime unavailable"),
        ):
            service = IntelligenceService(xiezhi_enabled=True)
            decision = service.decide(make_outcome())
        self.assertEqual(decision.provider_id, "gongshu")
        self.assertEqual(decision.algorithm_id, "baseline_topk")
        self.assertTrue(decision.used_fallback)
        self.assertTrue(decision.authorizes_execution)
        self.assertEqual(service.snapshot()["status"], "DEGRADED")

    def test_experiment_lab_record_contains_input_algorithm_decision_and_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts" / "offline_run"
            adapter = LocalImageAdapter(root)
            observation = adapter.load("sample.png", image_bytes())
            recorder = ExperimentTrialRecorder(root)
            recorder.start(observation)
            decision = IntelligenceService(xiezhi_enabled=False).decide(make_outcome())
            recorder.record_decision(observation.run_id, decision)
            recorder.record_result(observation.run_id, {"status": "SUCCESS"})
            record = json.loads(
                (root / observation.run_id / "experiment_record.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(record["input"]["sha256"], observation.sha256)
            self.assertEqual(record["algorithm"]["algorithm"], "baseline_topk")
            self.assertEqual(
                record["decision"]["selected_candidate_id"], "candidate-01"
            )
            self.assertEqual(record["mujoco_result"]["status"], "SUCCESS")
            self.assertEqual(record["status"], "COMPLETED")

    def test_gongshu_execution_consumes_decision_before_mujoco(self) -> None:
        outcome = make_outcome()
        captured: list[tuple[object, str, object]] = []

        class Planning:
            @staticmethod
            def current_outcome():
                return outcome

        class Target:
            @staticmethod
            def selected_scene_snapshot():
                return SimpleNamespace(snapshot_id="snapshot-42")

        class Validation:
            @staticmethod
            def start(plan, *, scenario, snapshot):
                captured.append((plan, scenario, snapshot))
                return {"status": "INITIALIZING"}

        app = object.__new__(Vision2GraspApp)
        app.grasp_planning = Planning()
        app.target_perception = Target()
        app.mujoco_validation = Validation()
        app.intelligence = IntelligenceService(xiezhi_enabled=False)
        app._vision_source = "phone_camera"
        app._record_offline_pipeline_status = lambda _status: None
        app._start_offline_run_watch = lambda: None
        app._start_xiezhi_lifecycle = lambda **_kwargs: None

        response = app.start_validation(
            {"target_id": "target-42-01", "scenario": "NOMINAL"}
        )
        self.assertEqual(response["status"], "INITIALIZING")
        self.assertEqual(len(captured), 1)
        self.assertEqual(
            app.intelligence.snapshot()["last_decision"]["selected_action"],
            "EXECUTE_GRASP",
        )


if __name__ == "__main__":
    unittest.main()
