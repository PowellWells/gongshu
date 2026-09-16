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
from vision2grasp.grasp_planning import (
    CandidateFeasibility,
    GraspCandidate,
    GraspConfidence,
    GraspPlan,
    PlanningState,
)
from vision2grasp.intelligence import (
    AlgorithmDecision,
    DecisionAction,
    DecisionStatus,
    IntelligenceService,
)
from vision2grasp.sources import LocalImageAdapter
from vision2grasp.spatial_perception import CalibrationState, DepthMode, IntrinsicsSource


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
    if plan is not None:
        plan.for_execution_candidate = lambda _candidate_id: plan
    return SimpleNamespace(
        candidates=(candidate,),
        plan=plan,
        planning_time_s=0.02,
        grasp_uncertainty=None,
        spatial_uncertainty=None,
    )


def make_three_candidate_outcome():
    candidates = tuple(
        GraspCandidate(
            candidate_id=candidate_id,
            grasp_point_xyz=np.array([x, 0.0, 0.73]),
            approach_vector=np.array([0.0, 0.0, 1.0]),
            closing_vector=np.array([1.0, 0.0, 0.0]),
            grasp_angle=0.0,
            gripper_width=0.04,
            quality_score=score,
            score_factors={"quality": score},
            ranking_score=score,
            source_frame_id=42,
            target_instance_id="target-42-01",
        )
        for candidate_id, x, score in (
            ("C1", 0.01, 0.95),
            ("C2", 0.02, 0.85),
            ("C3", 0.03, 0.75),
        )
    )
    plan = GraspPlan(
        target_id="target-42-01",
        snapshot_id="snapshot-42",
        source_frame_id=42,
        grasp_point_xyz=candidates[0].grasp_point_xyz,
        approach_vector=candidates[0].approach_vector,
        closing_vector=candidates[0].closing_vector,
        grasp_angle=candidates[0].grasp_angle,
        gripper_width=candidates[0].gripper_width,
        quality_score=candidates[0].quality_score,
        confidence=GraspConfidence(value=0.90, factors={"quality": 0.90}),
        source="test",
        coordinate_frame="OPENCV_CAMERA_X_RIGHT_Y_DOWN_Z_FORWARD",
        depth_mode=DepthMode.METRIC,
        planning_state=PlanningState.GRASP_READY,
        intrinsics_source=IntrinsicsSource.CALIBRATED,
        calibration_state=CalibrationState.CALIBRATED,
        uncertainty=(),
        object_extents_xyz=np.array([0.10, 0.08, 0.12]),
        candidate_count=3,
        candidates=candidates,
        best_candidate_id="C1",
    )
    return SimpleNamespace(
        candidates=candidates,
        plan=plan,
        planning_time_s=0.02,
        grasp_uncertainty=None,
        spatial_uncertainty=None,
    )


def make_decision(action: DecisionAction, candidate_id: str | None = None):
    return AlgorithmDecision(
        decision_id=f"decision-{action.value.lower()}",
        observation_id="observation-42",
        provider_id="xiezhi",
        algorithm_id="test_authority",
        status=DecisionStatus.ACTION_AVAILABLE,
        selected_action=action,
        selected_candidate_id=candidate_id,
        confidence=0.88,
        risk_estimation=0.12,
        uncertainty=("DEPTH_UNRELIABLE",),
        reason="test_decision",
        diagnostics={"test": True},
    )


def image_bytes() -> bytes:
    bgr = np.full((8, 12, 3), 80, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("test image encoding failed")
    return encoded.tobytes()


class IntelligenceRuntimeTests(unittest.TestCase):
    def test_xiezhi_v0_1_provider_selects_candidate_through_standard_interface(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)
        decision = service.decide(make_outcome())
        self.assertEqual(decision.provider_id, "xiezhi")
        self.assertEqual(decision.algorithm_id, "xiezhi_decision_v0_1")
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
        xiezhi_entry = next(
            entry
            for entry in state["available_algorithms"]
            if entry["provider"] == "xiezhi"
        )
        self.assertEqual(xiezhi_entry["algorithm"], "xiezhi_decision_v0_1")
        self.assertEqual(xiezhi_entry["name"], "Xiezhi Decision")
        self.assertEqual(xiezhi_entry["version"], "v0.1")
        self.assertEqual(xiezhi_entry["type"], "Xiezhi Algorithm")
        self.assertEqual(xiezhi_entry["decision_contract"], "gongshu.intelligence-decision/v1")
        payload = decision.public_metadata()
        self.assertEqual(payload["action"], "EXECUTE_GRASP")
        self.assertEqual(payload["uncertainty"], [])
        self.assertTrue(
            {
                "selected_candidate_id",
                "action",
                "confidence",
                "risk_estimation",
                "uncertainty",
                "reason",
                "diagnostics",
            }.issubset(payload)
        )

    def test_service_exposes_dashboard_v1_as_a_read_only_decision_projection(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)
        self.assertIsNone(service.dashboard_state())
        decision = service.decide(make_outcome())

        dashboard = service.dashboard_state()

        self.assertIsNotNone(dashboard)
        assert dashboard is not None
        payload = dashboard.public_metadata()
        self.assertEqual(payload["schema_version"], "gongshu.xiezhi-dashboard/v1")
        self.assertEqual(payload["runtime"]["current_action"], decision.action.value)
        self.assertEqual(
            payload["runtime"]["selected_candidate"],
            decision.selected_candidate_id,
        )
        self.assertEqual(payload["engine"]["algorithm_version"], "v0.1")

        baseline = IntelligenceService(xiezhi_enabled=False)
        baseline.decide(make_outcome())
        self.assertIsNone(baseline.dashboard_state())

    def test_decision_engine_can_switch_to_baseline_and_preserve_history(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)
        first = service.decide(make_outcome())
        selected = service.select_algorithm("gongshu", "baseline_topk")
        self.assertEqual(selected["selected_provider"], "gongshu")
        self.assertEqual(selected["selected_algorithm"], "baseline_topk")
        self.assertFalse(selected["decision_available"])
        second = service.decide(make_outcome())
        self.assertEqual(first.provider_id, "xiezhi")
        self.assertEqual(second.provider_id, "gongshu")
        history = service.snapshot()["decision_history"]
        self.assertEqual([item["provider"] for item in history], ["gongshu", "xiezhi"])

    def test_unknown_decision_engine_is_rejected(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)
        with self.assertRaisesRegex(ValueError, "not available"):
            service.select_algorithm("xiezhi", "not_registered")

    def test_xiezhi_runtime_failure_falls_back_to_gongshu_baseline(self) -> None:
        with patch(
            "vision2grasp.extensions.xiezhi.algorithms.decision_v0_1.XiezhiDecisionV01.decide",
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

    def test_xiezhi_selected_candidate_overrides_planner_best_for_runtime(self) -> None:
        outcome = make_three_candidate_outcome()
        selected_decision = make_decision(DecisionAction.EXECUTE_GRASP, "C2")
        captured: list[object] = []

        class Planning:
            @staticmethod
            def current_outcome():
                return outcome

        class Intelligence:
            @staticmethod
            def ensure_decision(_outcome):
                return selected_decision

        class Target:
            @staticmethod
            def selected_scene_snapshot():
                return SimpleNamespace(snapshot_id="snapshot-42")

        class Validation:
            @staticmethod
            def start(plan, *, scenario, snapshot):
                captured.append(plan)
                return {"status": "INITIALIZING", "candidate_id": plan.best_candidate_id}

        app = object.__new__(Vision2GraspApp)
        app.grasp_planning = Planning()
        app.intelligence = Intelligence()
        app.target_perception = Target()
        app.mujoco_validation = Validation()
        app._vision_source = "phone_camera"
        app._record_offline_pipeline_status = lambda _status: None
        app._start_offline_run_watch = lambda: None
        app._start_xiezhi_lifecycle = lambda **_kwargs: None

        response = app.start_validation(
            {"target_id": "target-42-01", "scenario": "NOMINAL"}
        )

        self.assertEqual(outcome.plan.best_candidate_id, "C1")
        self.assertEqual(response["candidate_id"], "C2")
        self.assertEqual(captured[0].best_candidate_id, "C2")
        np.testing.assert_allclose(captured[0].grasp_point_xyz, [0.02, 0.0, 0.73])

    def test_reobserve_and_abort_never_start_mujoco(self) -> None:
        outcome = make_three_candidate_outcome()

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
            def start(*_args, **_kwargs):
                raise AssertionError("MuJoCo must not start")

        app = object.__new__(Vision2GraspApp)
        app.grasp_planning = Planning()
        app.target_perception = Target()
        app.mujoco_validation = Validation()
        app._vision_source = "phone_camera"

        for action, message in (
            (DecisionAction.REOBSERVE, "requires reobservation"),
            (DecisionAction.ABORT, "aborted the current task"),
        ):
            with self.subTest(action=action):
                decision = make_decision(action)
                app.intelligence = SimpleNamespace(
                    ensure_decision=lambda _outcome, value=decision: value
                )
                with self.assertRaisesRegex(RuntimeError, message):
                    app.start_validation({"target_id": "target-42-01"})


if __name__ == "__main__":
    unittest.main()
