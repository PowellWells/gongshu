from __future__ import annotations

import importlib
import tomllib
import unittest
from pathlib import Path

import numpy as np

import vision2grasp
from vision2grasp import (
    CameraIntrinsics,
    Detection2D,
    ExecutionPhase,
    ExecutionResult,
    GraspCandidate,
    RGBDFrame,
)


ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intrinsics = CameraIntrinsics(640, 480, 600.0, 600.0, 320.0, 240.0)

    def test_rgbd_frame_accepts_expected_shapes(self) -> None:
        frame = RGBDFrame(
            frame_id=1,
            timestamp_s=0.0,
            camera_name="agentview",
            rgb=np.zeros((480, 640, 3), dtype=np.uint8),
            depth_m=np.ones((480, 640), dtype=np.float32),
            intrinsics=self.intrinsics,
            world_from_camera=np.eye(4, dtype=np.float64),
        )
        self.assertEqual(frame.rgb.shape, (480, 640, 3))

    def test_rgbd_frame_rejects_mismatched_depth(self) -> None:
        with self.assertRaises(ValueError):
            RGBDFrame(
                frame_id=1,
                timestamp_s=0.0,
                camera_name="agentview",
                rgb=np.zeros((480, 640, 3), dtype=np.uint8),
                depth_m=np.ones((240, 320), dtype=np.float32),
                intrinsics=self.intrinsics,
                world_from_camera=np.eye(4, dtype=np.float64),
            )

    def test_detection_and_grasp_score_validation(self) -> None:
        detection = Detection2D(
            class_id=39,
            class_name="bottle",
            confidence=0.9,
            bbox_xyxy=(10.0, 20.0, 100.0, 200.0),
            mask=np.ones((480, 640), dtype=np.bool_),
        )
        candidate = GraspCandidate(
            candidate_id="candidate-0",
            world_from_grasp=np.eye(4, dtype=np.float64),
            gripper_width_m=0.05,
            score=0.8,
            reachable=True,
            score_terms={"confidence": detection.confidence},
        )
        self.assertTrue(candidate.reachable)

    def test_execution_result_requires_consistent_terminal_phase(self) -> None:
        result = ExecutionResult(
            candidate_id="candidate-0",
            success=True,
            final_phase=ExecutionPhase.SUCCEEDED,
            message="lifted",
            visited_phases=(ExecutionPhase.HOME, ExecutionPhase.LIFT, ExecutionPhase.SUCCEEDED),
        )
        self.assertTrue(result.success)
        with self.assertRaises(ValueError):
            ExecutionResult(
                candidate_id="candidate-0",
                success=False,
                final_phase=ExecutionPhase.SUCCEEDED,
                message="invalid",
                visited_phases=(),
            )


class BoundaryTests(unittest.TestCase):
    def test_all_pipeline_packages_import(self) -> None:
        for package in (
            "simulation",
            "perception",
            "geometry",
            "grasp",
            "control",
            "visualization",
            "evaluation",
        ):
            importlib.import_module(f"vision2grasp.{package}")

    def test_ground_truth_is_not_exported_from_public_root(self) -> None:
        self.assertFalse(hasattr(vision2grasp, "GroundTruthObjectPose"))
        self.assertFalse(hasattr(vision2grasp, "GroundTruthProvider"))

    def test_default_config_freezes_stage_zero_versions(self) -> None:
        with (ROOT / "configs" / "default.toml").open("rb") as handle:
            config = tomllib.load(handle)
        self.assertEqual(config["simulation"]["mujoco_version"], "3.9.0")
        self.assertEqual(config["simulation"]["robosuite_version"], "1.5.2")
        self.assertFalse(config["grasp"]["use_simulation_truth"])


if __name__ == "__main__":
    unittest.main()
