from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

import cv2
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
from vision2grasp.pipeline import PipelinePhase, PipelineRunResult
from vision2grasp.visualization import (
    RUN_SCHEMA_VERSION,
    RunArtifactExporter,
    make_run_id,
)


ROOT = Path(__file__).resolve().parents[1]


def _frame(frame_id: int = 1) -> RGBDFrame:
    height, width = 32, 40
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[..., 2] = 80
    depth = np.linspace(0.7, 1.0, height * width, dtype=np.float32).reshape(
        height, width
    )
    return RGBDFrame(
        frame_id=frame_id,
        timestamp_s=float(frame_id),
        camera_name="frontview",
        rgb=rgb,
        depth_m=depth,
        intrinsics=CameraIntrinsics(width, height, 30.0, 30.0, 20.0, 16.0),
        world_from_camera=np.eye(4, dtype=np.float64),
    )


def _successful_run() -> PipelineRunResult:
    frame = _frame()
    mask = np.zeros(frame.depth_m.shape, dtype=np.bool_)
    mask[8:25, 12:29] = True
    detection = Detection2D(
        class_id=39,
        class_name="bottle",
        confidence=0.8,
        bbox_xyxy=(12.0, 8.0, 29.0, 25.0),
        mask=mask,
    )
    points = np.array(
        [[-0.01, -0.01, 0.9], [0.01, 0.01, 0.9], [0.0, 0.0, 0.92]],
        dtype=np.float64,
    )
    target = LocalizedTarget(
        detection=detection,
        centroid_world_m=np.mean(points, axis=0),
        points_world_m=points,
        depth_valid_ratio=1.0,
    )
    pose = np.diag([1.0, -1.0, -1.0, 1.0]).astype(np.float64)
    pose[:3, 3] = [0.0, 0.0, 0.9]
    candidate = GraspCandidate(
        candidate_id="top-pca-39-0",
        world_from_grasp=pose,
        gripper_width_m=0.048,
        score=0.79,
        reachable=True,
    )
    execution = ExecutionResult(
        candidate_id=candidate.candidate_id,
        success=True,
        final_phase=ExecutionPhase.SUCCEEDED,
        message="motion sequence completed",
        visited_phases=(
            ExecutionPhase.HOME,
            ExecutionPhase.PREGRASP,
            ExecutionPhase.DESCEND,
            ExecutionPhase.CLOSE,
            ExecutionPhase.LIFT,
            ExecutionPhase.RETURN_HOME,
            ExecutionPhase.SUCCEEDED,
        ),
    )
    return PipelineRunResult(
        success=True,
        final_phase=PipelinePhase.SUCCEEDED,
        message="truth-free perception-to-motion sequence completed",
        visited_phases=(
            PipelinePhase.CAPTURE,
            PipelinePhase.DETECT,
            PipelinePhase.LOCALIZE,
            PipelinePhase.PLAN,
            PipelinePhase.EXECUTE,
            PipelinePhase.SUCCEEDED,
        ),
        frame=frame,
        detections=(detection,),
        selected_detection=detection,
        localized_target=target,
        candidates=(candidate,),
        selected_candidate=candidate,
        execution=execution,
    )


class RunArtifactExporterTests(unittest.TestCase):
    def test_exports_v1_json_and_four_public_png_views(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            exported = RunArtifactExporter().export(
                _successful_run(),
                output_root=Path(temporary_directory),
                run_id="bottle-seed7-test",
                timestamp=datetime(2026, 8, 26, 14, 30, tzinfo=timezone.utc),
                final_frame=_frame(frame_id=2),
            )

            document = json.loads(exported.run_json_path.read_text(encoding="utf-8"))
            self.assertEqual(document["schema_version"], RUN_SCHEMA_VERSION)
            self.assertEqual(document["status"], "success")
            self.assertEqual(document["stage"], "SUCCESS")
            self.assertEqual(document["target"]["class_name"], "bottle")
            self.assertEqual(document["target"]["image_size_px"], {"width": 40, "height": 32})
            self.assertEqual(document["selected_candidate_id"], "top-pca-39-0")
            self.assertEqual(document["candidates"][0]["rank"], 1)
            self.assertEqual(document["execution"]["final_phase"], "SUCCESS")
            self.assertNotIn("evaluation", document)
            event_stages = [event["stage"] for event in document["events"]]
            self.assertLess(event_stages.index("LIFT"), event_stages.index("SUCCEEDED"))

            for key in ("rgb", "depth", "grasp_overlay", "mujoco"):
                media = document["media"][key]
                self.assertEqual(media["kind"], "image")
                self.assertNotIn("\\", media["path"])
                image_path = exported.run_directory / media["path"]
                self.assertTrue(image_path.is_file(), image_path)
                self.assertIsNotNone(cv2.imread(str(image_path)))

    def test_failure_export_uses_null_partial_fields_and_never_truth(self) -> None:
        run = PipelineRunResult(
            success=False,
            final_phase=PipelinePhase.FAILED,
            message="detection produced no target instances",
            visited_phases=(
                PipelinePhase.CAPTURE,
                PipelinePhase.DETECT,
                PipelinePhase.FAILED,
            ),
            frame=_frame(),
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            document = RunArtifactExporter().export(
                run,
                output_root=Path(temporary_directory),
                run_id="failed-run",
                timestamp=datetime(2026, 8, 26, tzinfo=timezone.utc),
            ).document

        self.assertEqual(document["status"], "failure")
        self.assertEqual(document["stage"], "FAILURE")
        self.assertIsNone(document["target"])
        self.assertEqual(document["candidates"], [])
        self.assertIsNone(document["execution"])
        self.assertIsNone(document["media"]["mujoco"])
        self.assertEqual(document["events"][-1]["status"], "failed")
        self.assertNotIn("evaluation", json.dumps(document))

    def test_rejects_unsafe_or_overwriting_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            with self.assertRaises(ValueError):
                RunArtifactExporter().export(
                    _successful_run(), output_root=output_root, run_id="../outside"
                )
            RunArtifactExporter().export(
                _successful_run(), output_root=output_root, run_id="same-run"
            )
            with self.assertRaises(FileExistsError):
                RunArtifactExporter().export(
                    _successful_run(), output_root=output_root, run_id="same-run"
                )

    def test_schema_and_generated_id_publish_the_frozen_version(self) -> None:
        schema = json.loads(
            (ROOT / "contracts" / "run-v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema["properties"]["schema_version"]["const"], RUN_SCHEMA_VERSION
        )
        run_id = make_run_id(
            "bottle-lift-seed7",
            timestamp=datetime(2026, 8, 26, 14, 30, tzinfo=timezone.utc),
        )
        self.assertRegex(run_id, r"^bottle-lift-seed7-20260826T143000\d{6}p0000$")


if __name__ == "__main__":
    unittest.main()
