from __future__ import annotations

import json
import threading
import time
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from vision2grasp.contracts import CameraIntrinsics
from vision2grasp.grasp_planning import (
    AbnormalScaleError,
    EmptyPointCloudError,
    GeometricGraspPlanner,
    GraspPlanningService,
    GripperWidthError,
)
from vision2grasp.simulation import (
    CameraDirector,
    MuJoCoValidationService,
    NativePandaValidation,
    NativePandaValidationConfig,
    SimulationState,
    ValidationRequest,
    ValidationResult,
    ValidationScenario,
)
from vision2grasp.spatial_perception import (
    CalibrationState,
    DepthFrame,
    DepthMode,
    DepthSource,
    GeometrySanity,
    GeometrySanityStatus,
    IntrinsicsObservation,
    IntrinsicsSource,
    SpatialObservation,
    TargetDepth,
)
from vision2grasp.target_perception import TargetInstance, TargetSceneSnapshot
from vision2grasp.contracts import RGBFrame


def make_observation(
    *,
    width_m: float = 0.04,
    length_m: float = 0.08,
    depth_m: float = 0.03,
    points_per_axis: int = 35,
) -> SpatialObservation:
    long_axis = np.array([np.cos(0.42), np.sin(0.42)])
    short_axis = np.array([-long_axis[1], long_axis[0]])
    samples = []
    for major in np.linspace(-length_m / 2.0, length_m / 2.0, points_per_axis):
        for minor in np.linspace(-width_m / 2.0, width_m / 2.0, points_per_axis):
            if (major / (length_m / 2.0)) ** 2 + (minor / (width_m / 2.0)) ** 2 <= 1.0:
                xy = long_axis * major + short_axis * minor
                z = 0.72 + depth_m * (0.5 + 0.5 * np.sin(major * 91.0))
                samples.append([xy[0], xy[1], z])
    points = np.asarray(samples, dtype=np.float32)
    depth = np.full((48, 64), 0.735, dtype=np.float32)
    return SpatialObservation(
        snapshot_id="snapshot-42",
        geometry_chain_id="geometry-test-42",
        source_frame_id=42,
        target_instance_id="target-42-01",
        source_timestamp_s=12.5,
        depth_frame=DepthFrame(
            source_frame_id=42,
            source_timestamp_s=12.5,
            values=depth,
            source=DepthSource.MONOCULAR,
            native_mode=DepthMode.METRIC,
        ),
        target_depth=TargetDepth(
            value=0.735,
            valid_ratio=0.96,
            inlier_ratio=0.91,
            valid_pixel_count=1000,
            inlier_pixel_count=910,
        ),
        centroid_xyz=np.median(points, axis=0),
        target_point_cloud=points,
        camera_intrinsics=IntrinsicsObservation(
            CameraIntrinsics(width=64, height=48, fx=52.0, fy=52.0, cx=31.5, cy=23.5),
            IntrinsicsSource.NOMINAL_FOV,
            CalibrationState.UNCALIBRATED,
            nominal_fov_deg=75.0,
        ),
        depth_source=DepthSource.MONOCULAR,
        depth_mode=DepthMode.APPROX_METRIC,
        inference_time_s=0.1,
        geometry_sanity=GeometrySanity(
            GeometrySanityStatus.PASS,
            ("SAME_SNAPSHOT_COORDINATES",),
        ),
    )


def make_snapshot() -> TargetSceneSnapshot:
    rgb = np.zeros((48, 64, 3), dtype=np.uint8)
    rgb[..., 1] = 70
    mask = np.zeros((48, 64), dtype=np.bool_)
    mask[10:39, 15:51] = True
    return TargetSceneSnapshot(
        "snapshot-42",
        RGBFrame(42, 12.5, "phone-frozen", rgb),
        TargetInstance(
            instance_id="target-42-01",
            mask=mask,
            bbox_xyxy=(15.0, 10.0, 51.0, 39.0),
            centroid_2d=(32.5, 24.0),
            source_frame_id=42,
            source_timestamp_s=12.5,
        ),
    )


class GeometricGraspPlanningTests(unittest.TestCase):
    def test_empty_cloud_is_rejected(self) -> None:
        with self.assertRaises(EmptyPointCloudError):
            GeometricGraspPlanner().plan(SimpleNamespace(target_point_cloud=np.empty((0, 3))))

    def test_single_target_generates_candidates_selects_best_and_serializes(self) -> None:
        plan, candidates = GeometricGraspPlanner().plan(make_observation())
        self.assertEqual(len(candidates), 3)
        self.assertEqual(plan.candidate_count, 3)
        self.assertEqual(plan.target_id, "target-42-01")
        self.assertEqual(plan.depth_mode, DepthMode.APPROX_METRIC)
        self.assertEqual(plan.calibration_state, CalibrationState.UNCALIBRATED)
        self.assertEqual(plan.confidence.type.value, "HEURISTIC_UNCALIBRATED")
        self.assertEqual(
            set(plan.confidence.factors),
            {"point_support", "depth_validity", "pca_stability", "width_margin"},
        )
        self.assertIn("APPROX_METRIC_INPUT", plan.uncertainty)
        self.assertIn("UNCALIBRATED_INTRINSICS", plan.uncertainty)
        self.assertTrue(0.01 <= plan.gripper_width <= 0.08)
        self.assertEqual(plan.quality_score, max(candidate.quality_score for candidate in candidates))
        encoded = json.dumps(plan.public_metadata())
        self.assertIn("gongshu.grasp-plan/v2", encoded)
        self.assertIn("ROBOT_INDEPENDENT_CAMERA_FRAME", encoded)

    def test_abnormal_scale_and_width_limit_fail_without_clamping(self) -> None:
        with self.assertRaises(AbnormalScaleError):
            GeometricGraspPlanner().plan(make_observation(length_m=0.48, width_m=0.04))
        with self.assertRaises(GripperWidthError) as captured:
            GeometricGraspPlanner().plan(make_observation(width_m=0.095, length_m=0.12))
        self.assertIn("outside", str(captured.exception))

    def test_service_association_and_real_overlay(self) -> None:
        service = GraspPlanningService()
        state = service.plan(make_observation(), make_snapshot())
        deadline = time.monotonic() + 2.0
        while state["status"] == "PLANNING" and time.monotonic() < deadline:
            time.sleep(0.01)
            state = service.snapshot()
        self.assertEqual(state["status"], "GRASP_READY")
        self.assertTrue(state["media"]["overlay_available"])
        self.assertGreater(len(service.overlay_jpeg() or b""), 100)


class _FakeValidationBackend:
    def __init__(self, request: ValidationRequest, director: CameraDirector, *, fail: bool = False) -> None:
        self.request = request
        self.fail = fail

    def run(self, callback, stop_event: threading.Event) -> ValidationResult:
        for state in (
            SimulationState.HOME,
            SimulationState.PRE_GRASP,
            SimulationState.APPROACH,
            SimulationState.ALIGN,
            SimulationState.CLOSE,
            SimulationState.LIFT,
            SimulationState.VERIFY,
        ):
            callback(state, b"real-frame", {"target_id": self.request.grasp_plan.target_id})
        if self.fail:
            return ValidationResult(SimulationState.FAILED, "Lift Failed", True, False, True, 0.0, False)
        return ValidationResult(SimulationState.SUCCESS, None, True, False, True, 0.12, True)


class MuJoCoValidationStateTests(unittest.TestCase):
    @staticmethod
    def _ready_plan():
        return GeometricGraspPlanner().plan(make_observation())[0]

    @staticmethod
    def _wait(service: MuJoCoValidationService) -> dict[str, object]:
        deadline = time.monotonic() + 3.0
        state = service.snapshot()
        while state["status"] not in {"SUCCESS", "FAILED"} and time.monotonic() < deadline:
            time.sleep(0.01)
            state = service.snapshot()
        return state

    def test_normalized_transform_does_not_claim_camera_robot_calibration(self) -> None:
        request = ValidationRequest.from_grasp_plan(self._ready_plan())
        metadata = request.public_metadata()
        self.assertEqual(metadata["scene_transform"]["name"], "NORMALIZED_VALIDATION_SCENE")
        self.assertEqual(metadata["scene_transform"]["calibration_state"], "UNCALIBRATED")
        self.assertEqual(metadata["scene_transform"]["execution_scope"], "SIMULATION_ONLY")
        self.assertNotEqual(
            metadata["scene_transform"]["target_position_world"],
            metadata["grasp_plan"]["grasp_point_xyz"],
        )

    def test_target_offset_stress_changes_only_simulated_target_pose(self) -> None:
        request = ValidationRequest.from_grasp_plan(
            self._ready_plan(),
            scenario=ValidationScenario.TARGET_OFFSET_STRESS,
            failure_target_offset_m=(0.14, 0.0, 0.0),
        )
        transform = request.scene_transform
        np.testing.assert_allclose(transform.target_offset_world, [0.14, 0.0, 0.0])
        np.testing.assert_allclose(
            transform.target_position_world - transform.grasp_position_world,
            transform.target_offset_world,
        )
        self.assertEqual(request.public_metadata()["scene_transform"]["scenario"], "TARGET_OFFSET_STRESS")

    def test_state_transitions_stream_frames_and_succeed(self) -> None:
        service = MuJoCoValidationService(lambda request, director: _FakeValidationBackend(request, director))
        started = service.start(self._ready_plan())
        self.assertIn(started["status"], {"INITIALIZING", "HOME", "PRE_GRASP", "APPROACH", "ALIGN", "CLOSE", "LIFT", "VERIFY", "SUCCESS"})
        finished = self._wait(service)
        self.assertEqual(finished["status"], "SUCCESS")
        self.assertEqual(finished["result"]["validation_result"], "Simulation Validation SUCCESS")
        self.assertTrue(finished["media"]["stream_available"])
        self.assertIsNotNone(service.wait_for_frame(-1, timeout=0.1))

    def test_failure_fallback_preserves_real_reason(self) -> None:
        service = MuJoCoValidationService(lambda request, director: _FakeValidationBackend(request, director, fail=True))
        service.start(self._ready_plan())
        finished = self._wait(service)
        self.assertEqual(finished["status"], "FAILED")
        self.assertEqual(finished["reason"], "Lift Failed")
        self.assertEqual(finished["result"]["lift_height_m"], 0.0)

    def test_service_exposes_scenario_and_state_history(self) -> None:
        service = MuJoCoValidationService(
            lambda request, director: _FakeValidationBackend(request, director)
        )
        started = service.start(
            self._ready_plan(),
            scenario=ValidationScenario.TARGET_OFFSET_STRESS,
        )
        self.assertEqual(started["scenario"], "TARGET_OFFSET_STRESS")
        finished = self._wait(service)
        self.assertEqual(finished["scenario"], "TARGET_OFFSET_STRESS")
        self.assertEqual(finished["state_history"][0]["state"], "INITIALIZING")
        self.assertEqual(finished["state_history"][-1]["state"], "SUCCESS")


class NativeMuJoCoPhysicsSmokeTest(unittest.TestCase):
    def test_dynamic_contact_lifts_target_without_pose_binding(self) -> None:
        request = ValidationRequest.from_grasp_plan(GeometricGraspPlanner().plan(make_observation())[0])
        backend = NativePandaValidation(
            request,
            CameraDirector(),
            NativePandaValidationConfig(
                width=320,
                height=180,
                render_fps=4,
                stable_window_s=0.2,
                realtime_playback=False,
            ),
        )
        states: set[str] = set()
        result = backend.run(
            lambda state, jpeg, telemetry: states.add(state.value),
            threading.Event(),
        )
        self.assertTrue({"HOME", "PRE_GRASP", "APPROACH", "ALIGN", "CLOSE", "LIFT", "VERIFY"}.issubset(states))
        self.assertEqual(result.state, SimulationState.SUCCESS)
        self.assertGreaterEqual(result.lift_height_m, 0.08)
        self.assertFalse(result.invalid_table_collision)
        self.assertTrue(result.stable_window_passed)

    def test_target_offset_stress_animates_physical_failure(self) -> None:
        request = ValidationRequest.from_grasp_plan(
            GeometricGraspPlanner().plan(make_observation())[0],
            scenario=ValidationScenario.TARGET_OFFSET_STRESS,
        )
        backend = NativePandaValidation(
            request,
            CameraDirector(),
            NativePandaValidationConfig(
                width=320,
                height=180,
                render_fps=4,
                stable_window_s=0.2,
                realtime_playback=False,
            ),
        )
        states: list[str] = []
        frames: list[bytes] = []
        result = backend.run(
            lambda state, jpeg, telemetry: (states.append(state.value), frames.append(jpeg)),
            threading.Event(),
        )
        self.assertEqual(result.state, SimulationState.FAILED)
        self.assertIn(result.reason, {"Lift Failed", "Collision", "Stability Failed"})
        self.assertIn("LIFT", states)
        self.assertEqual(states[-1], "FAILED")
        self.assertGreater(len(frames[-1]), 100)
        decoded = cv2.imdecode(np.frombuffer(frames[-1], dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertGreater(float(np.mean(decoded[:8, :, 2])), float(np.mean(decoded[:8, :, 0])))


if __name__ == "__main__":
    unittest.main()
