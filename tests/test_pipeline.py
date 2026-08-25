from __future__ import annotations

import inspect
import tomllib
import unittest
from pathlib import Path

import numpy as np

from vision2grasp import (
    CameraIntrinsics,
    Detection2D,
    ExecutionPhase,
    ExecutionResult,
    GraspCandidate,
    LocalizedTarget,
    RGBDFrame,
)
from vision2grasp.pipeline import PipelinePhase, Vision2GraspPipeline
import vision2grasp.pipeline as pipeline_module


def _frame() -> RGBDFrame:
    return RGBDFrame(
        frame_id=4,
        timestamp_s=0.2,
        camera_name="frontview",
        rgb=np.zeros((4, 5, 3), dtype=np.uint8),
        depth_m=np.ones((4, 5), dtype=np.float32),
        intrinsics=CameraIntrinsics(5, 4, 10.0, 10.0, 2.5, 2.0),
        world_from_camera=np.eye(4, dtype=np.float64),
    )


def _detection(
    class_name: str, confidence: float, mask_pixels: int
) -> Detection2D:
    mask = np.zeros((4, 5), dtype=np.bool_)
    mask.reshape(-1)[:mask_pixels] = True
    return Detection2D(
        class_id=39 if class_name == "bottle" else 41,
        class_name=class_name,
        confidence=confidence,
        bbox_xyxy=(0.0, 0.0, 4.0, 3.0),
        mask=mask,
    )


def _candidate(candidate_id: str, score: float, reachable: bool) -> GraspCandidate:
    pose = np.diag([1.0, -1.0, -1.0, 1.0]).astype(np.float64)
    pose[:3, 3] = [0.0, 0.0, 0.9]
    return GraspCandidate(
        candidate_id=candidate_id,
        world_from_grasp=pose,
        gripper_width_m=0.04,
        score=score,
        reachable=reachable,
    )


class FakeSimulator:
    def __init__(self, frame: RGBDFrame) -> None:
        self.frame = frame

    def capture(self) -> RGBDFrame:
        return self.frame


class FakeSegmenter:
    model_name = "fake-segmenter"

    def __init__(self, detections: tuple[Detection2D, ...]) -> None:
        self.detections = detections

    def predict(self, _frame: RGBDFrame) -> tuple[Detection2D, ...]:
        return self.detections


class FakeLocalizer:
    def __init__(self, *, fails: bool = False) -> None:
        self.selected: Detection2D | None = None
        self.fails = fails

    def localize(
        self, _frame: RGBDFrame, detection: Detection2D
    ) -> LocalizedTarget:
        self.selected = detection
        if self.fails:
            raise ValueError("invalid depth")
        points = np.column_stack(
            (
                np.linspace(-0.01, 0.01, 30),
                np.linspace(0.01, -0.01, 30),
                np.full(30, 0.9),
            )
        )
        return LocalizedTarget(
            detection=detection,
            centroid_world_m=np.mean(points, axis=0),
            points_world_m=points,
            depth_valid_ratio=1.0,
        )


class FakePlanner:
    def __init__(self, candidates: tuple[GraspCandidate, ...]) -> None:
        self.candidates = candidates

    def plan(self, _target: LocalizedTarget) -> tuple[GraspCandidate, ...]:
        return self.candidates


class FakeExecutor:
    def __init__(self, *, succeeds: bool = True) -> None:
        self.succeeds = succeeds
        self.selected: GraspCandidate | None = None

    def execute(self, candidate: GraspCandidate) -> ExecutionResult:
        self.selected = candidate
        return ExecutionResult(
            candidate_id=candidate.candidate_id,
            success=self.succeeds,
            final_phase=(
                ExecutionPhase.SUCCEEDED if self.succeeds else ExecutionPhase.FAILED
            ),
            message="done" if self.succeeds else "blocked",
            visited_phases=(
                ExecutionPhase.HOME,
                ExecutionPhase.SUCCEEDED if self.succeeds else ExecutionPhase.FAILED,
            ),
        )


class PipelineTests(unittest.TestCase):
    def test_selects_deterministically_and_returns_complete_trace(self) -> None:
        cup = _detection("cup", 0.8, 12)
        bottle = _detection("bottle", 0.8, 8)
        localizer = FakeLocalizer()
        executor = FakeExecutor()
        candidates = (
            _candidate("unreachable", 1.0, False),
            _candidate("candidate-b", 0.7, True),
            _candidate("candidate-a", 0.7, True),
        )
        frame = _frame()
        pipeline = Vision2GraspPipeline(
            FakeSimulator(frame),  # type: ignore[arg-type]
            FakeSegmenter((cup, bottle)),
            localizer,
            FakePlanner(candidates),
            executor,
        )

        result = pipeline.run()

        self.assertTrue(result.success, result.message)
        self.assertEqual(
            result.visited_phases,
            (
                PipelinePhase.CAPTURE,
                PipelinePhase.DETECT,
                PipelinePhase.LOCALIZE,
                PipelinePhase.PLAN,
                PipelinePhase.EXECUTE,
                PipelinePhase.SUCCEEDED,
            ),
        )
        self.assertIs(localizer.selected, bottle)
        self.assertEqual(executor.selected.candidate_id, "candidate-a")  # type: ignore[union-attr]
        self.assertIs(result.frame, frame)
        self.assertEqual(
            result.selected_detection.class_name, "bottle"  # type: ignore[union-attr]
        )
        self.assertEqual(
            result.selected_candidate.candidate_id,  # type: ignore[union-attr]
            "candidate-a",
        )
        self.assertTrue(result.execution.success)  # type: ignore[union-attr]

    def test_reports_no_detection_without_calling_downstream(self) -> None:
        result = Vision2GraspPipeline(
            FakeSimulator(_frame()),  # type: ignore[arg-type]
            FakeSegmenter(()),
            FakeLocalizer(),
            FakePlanner((_candidate("unused", 0.8, True),)),
            FakeExecutor(),
        ).run()

        self.assertFalse(result.success)
        self.assertEqual(
            result.visited_phases,
            (PipelinePhase.CAPTURE, PipelinePhase.DETECT, PipelinePhase.FAILED),
        )
        self.assertIn("no target", result.message)
        self.assertIsNone(result.localized_target)

    def test_propagates_execution_failure_as_pipeline_failure(self) -> None:
        result = Vision2GraspPipeline(
            FakeSimulator(_frame()),  # type: ignore[arg-type]
            FakeSegmenter((_detection("bottle", 0.9, 10),)),
            FakeLocalizer(),
            FakePlanner((_candidate("candidate", 0.8, True),)),
            FakeExecutor(succeeds=False),
        ).run()

        self.assertFalse(result.success)
        self.assertEqual(
            result.visited_phases[-2:],
            (PipelinePhase.EXECUTE, PipelinePhase.FAILED),
        )
        self.assertIn("blocked", result.message)
        self.assertFalse(result.execution.success)  # type: ignore[union-attr]

    def test_reports_localization_failure_at_its_stage(self) -> None:
        result = Vision2GraspPipeline(
            FakeSimulator(_frame()),  # type: ignore[arg-type]
            FakeSegmenter((_detection("bottle", 0.9, 10),)),
            FakeLocalizer(fails=True),
            FakePlanner((_candidate("unused", 0.8, True),)),
            FakeExecutor(),
        ).run()

        self.assertFalse(result.success)
        self.assertEqual(
            result.visited_phases[-2:],
            (PipelinePhase.LOCALIZE, PipelinePhase.FAILED),
        )
        self.assertIn("invalid depth", result.message)

    def test_reports_when_all_plans_are_unreachable(self) -> None:
        result = Vision2GraspPipeline(
            FakeSimulator(_frame()),  # type: ignore[arg-type]
            FakeSegmenter((_detection("bottle", 0.9, 10),)),
            FakeLocalizer(),
            FakePlanner((_candidate("too-wide", 0.0, False),)),
            FakeExecutor(),
        ).run()

        self.assertFalse(result.success)
        self.assertEqual(
            result.visited_phases[-2:],
            (PipelinePhase.PLAN, PipelinePhase.FAILED),
        )
        self.assertIn("no reachable", result.message)

    def test_pipeline_has_no_evaluation_truth_dependency(self) -> None:
        source = inspect.getsource(pipeline_module)
        self.assertNotIn("vision2grasp.evaluation", source)
        self.assertNotIn("GroundTruthObjectPose", source)
        self.assertNotIn("_evaluation_object_pose", source)

    def test_default_toml_freezes_bottle_pipeline(self) -> None:
        path = Path(__file__).parents[1] / "configs" / "default.toml"
        with path.open("rb") as stream:
            pipeline = tomllib.load(stream)["pipeline"]

        self.assertEqual(pipeline["scene"], "BottleLift")
        self.assertEqual(pipeline["camera_name"], "frontview")
        self.assertEqual(pipeline["target_class_priority"], ["bottle", "cup"])
        self.assertEqual(pipeline["evaluation_object_name"], "bottle")
        self.assertEqual(pipeline["minimum_vertical_displacement_m"], 0.03)


if __name__ == "__main__":
    unittest.main()
