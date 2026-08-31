from __future__ import annotations

import json
import hashlib
import threading
import time
import tempfile
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
from vision2grasp.simulation.native_panda_validation import RecordingPlaybackRenderer
from vision2grasp.simulation.recording import load_recording, save_recording
from vision2grasp.simulation.recording import RecordingEvent, SimulationRecording, utc_timestamp
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


def make_minimal_recording(result: ValidationResult) -> SimulationRecording:
    model_xml = """<mujoco model='recording-test'><visual><global offwidth='160' offheight='90'/></visual><worldbody><body name='bottle_main' pos='0 0 0.8'><freejoint/><geom type='box' size='.03 .03 .06'/><site name='gripper0_right_grip_site' pos='0 0 .15' size='.01'/></body></worldbody></mujoco>"""
    target_poses = np.array([[0, 0, .8, 1, 0, 0, 0], [0, 0, .9, 1, 0, 0, 0]], dtype=np.float64)
    return SimulationRecording(
        recording_id="rec-test-session", run_id="run-test-session", created_at=utc_timestamp(),
        sample_hz=60.0, timestamps=np.array([0.0, 1.0]),
        qpos=target_poses.copy(), qvel=np.zeros((2, 6)), gripper_states=np.zeros((2, 2)),
        target_poses=target_poses, target_velocities=np.zeros((2, 6)),
        eef_positions=np.array([[0, 0, .95], [0, 0, 1.05]]),
        collision_states=np.array([False, result.invalid_table_collision]),
        lift_heights=np.array([0.0, result.lift_height_m]),
        validation_states=("HOME", result.state.value), contacts=((), ()),
        events=(RecordingEvent(0.0, "SIMULATION_STARTED", "HOME"),
                RecordingEvent(1.0, "VALIDATION_RESULT", result.state.value)),
        result=result,
        request_metadata={"grasp_plan": {"target_id": "target-42-01", "plan_id": "plan-test", "source_frame_id": 42}},
        compatibility={"mujoco_version": "3.9.0", "model_sha256": hashlib.sha256(model_xml.encode()).hexdigest(), "nq": 7, "nv": 6},
        model_xml=model_xml,
    )


class _RecordedFakeValidationBackend(_FakeValidationBackend):
    def run(self, callback, stop_event: threading.Event) -> ValidationResult:
        result = super().run(callback, stop_event)
        self.recording = make_minimal_recording(result)
        return result


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

    def test_recording_is_session_only_until_explicit_save_and_replay_controls_do_not_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = __import__("pathlib").Path(directory) / "recordings"
            service = MuJoCoValidationService(
                lambda request, director: _RecordedFakeValidationBackend(request, director),
                recordings_root=root,
            )
            try:
                service.start(self._ready_plan())
                finished = self._wait(service)
                deadline = time.monotonic() + 2.0
                while not finished["media"]["replay_available"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                    finished = service.snapshot()
                self.assertTrue(finished["media"]["replay_available"])
                self.assertFalse(finished["media"]["recording_saved"])
                self.assertFalse(root.exists())
                self.assertEqual(len(service.session_history()["session_history"]), 1)
                service.playback_control({"action": "SEEK", "time_s": 0.5})
                service.playback_control({"action": "STEP_FORWARD"})
                service.playback_control({"action": "SPEED", "speed": 0.25})
                state = service.set_camera_mode("TECHNICAL")
                self.assertEqual(state["camera_mode"], "TECHNICAL")
                self.assertEqual(state["playback"]["overlay_mode"], "TECHNICAL")
                saved = service.save_current_recording()
                self.assertTrue(saved["media"]["recording_saved"])
                self.assertTrue((root / "rec-test-session" / "states.npz").is_file())
            finally:
                service.close()

    def test_planning_rejection_creates_non_physics_session_visualization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = __import__("pathlib").Path(directory) / "recordings"
            service = MuJoCoValidationService(recordings_root=root)
            try:
                summary = service.record_planning_rejection(
                    {
                        "job_id": "grasp-rejected-width-test",
                        "status": "PLANNING_REJECTED",
                        "error_code": "GRIPPER_TOO_WIDE",
                        "visualization_request": {
                            "required_grasp_width_m": 0.095,
                            "maximum_gripper_width_m": 0.08,
                            "workspace_boundary": "PANDA_CONFIG",
                        },
                    },
                    b"jpeg-preview",
                )
                self.assertEqual(summary["kind"], "PLANNING_REJECTED_VISUALIZATION")
                self.assertFalse(root.exists())
                history = service.session_history()
                self.assertEqual(len(history["visualization_history"]), 1)
                opened = service.open_recording(summary["recording_id"])
                self.assertTrue(opened["media"]["visualization_available"])
                self.assertFalse(opened["media"]["replay_available"])
                self.assertIsNone(opened["playback"])
                saved = service.save_current_recording()
                self.assertTrue(saved["media"]["recording_saved"])
                self.assertTrue((root / summary["recording_id"] / "preview.jpg").is_file())
                restored_service = MuJoCoValidationService(recordings_root=root)
                try:
                    restored = restored_service.open_recording(summary["recording_id"], saved=True)
                    self.assertTrue(restored["media"]["visualization_available"])
                    self.assertEqual(
                        restored["recording"]["rejection_reason"],
                        "GRIPPER_TOO_WIDE",
                    )
                finally:
                    restored_service.close()
            finally:
                service.close()


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
        recording = backend.recording
        self.assertIsNotNone(recording)
        assert recording is not None
        self.assertIsNone(recording.saved_path)
        self.assertGreater(len(recording.timestamps), 300)
        self.assertAlmostEqual(recording.sample_hz, 60.0)
        self.assertEqual(recording.qpos.shape[0], len(recording.timestamps))
        self.assertEqual(recording.qvel.shape[0], len(recording.timestamps))
        self.assertEqual(recording.target_velocities.shape[1], 6)
        self.assertIn("PHASE_STARTED", {event.name for event in recording.events})
        with tempfile.TemporaryDirectory() as directory:
            root = __import__("pathlib").Path(directory)
            self.assertEqual(list(root.iterdir()), [])
            save_recording(recording, root)
            self.assertTrue((root / recording.recording_id / "manifest.json").is_file())
            restored = load_recording(recording.recording_id, root)
            np.testing.assert_allclose(restored.qpos, recording.qpos)
            self.assertEqual(restored.result.state, SimulationState.SUCCESS)

        # State restoration and camera changes must not advance physics.
        playback = RecordingPlaybackRenderer(recording, CameraDirector(), width=320, height=180)
        original_step = __import__("mujoco").mj_step
        try:
            __import__("mujoco").mj_step = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("playback called mj_step")
            )
            first, first_telemetry = playback.render_at(0.0)
            last, last_telemetry = playback.render_at(recording.duration_s)
        finally:
            __import__("mujoco").mj_step = original_step
            playback.close()
        self.assertGreater(len(first), 100)
        self.assertGreater(len(last), 100)
        self.assertEqual(first_telemetry["playback_source"], "RECORDED_MUJOCO_STATE")
        self.assertEqual(last_telemetry["robot_state"], "SUCCESS")

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
        self.assertIsNotNone(backend.recording)
        self.assertEqual(backend.recording.result.state, SimulationState.FAILED)
        self.assertEqual(backend.recording.validation_states[-1], "FAILED")
        self.assertGreater(len(frames[-1]), 100)
        decoded = cv2.imdecode(np.frombuffer(frames[-1], dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        self.assertGreater(float(np.mean(decoded[:8, :, 2])), float(np.mean(decoded[:8, :, 0])))


if __name__ == "__main__":
    unittest.main()
