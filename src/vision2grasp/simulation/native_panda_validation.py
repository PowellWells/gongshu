"""Continuous native-MuJoCo Panda validation driven only by ValidationRequest."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import threading
import time
from typing import Callable
import uuid
from xml.etree import ElementTree as ET

import cv2
import mujoco
import numpy as np

from vision2grasp.simulation.bottle_lift import BottleLift

from .appearance import ProxyGeometry, TARGET_TEXTURE_ASSET_NAME, TargetAppearance
from .validation_contracts import (
    CameraMode,
    SimulationState,
    SimulationFailureReason,
    ValidationRequest,
    ValidationResult,
)
from .recording import ContactState, RecordingEvent, SimulationRecording, utc_timestamp


FrameCallback = Callable[[SimulationState, bytes, dict[str, object]], None]
TARGET_BOX_VISUAL_MESH_ASSET_NAME = "target_box_appearance.obj"


@dataclass(frozen=True, slots=True)
class NativePandaValidationConfig:
    width: int = 960
    height: int = 540
    render_fps: int = 24
    recording_hz: float = 60.0
    lift_height_m: float = 0.08
    stable_window_s: float = 0.45
    realtime_playback: bool = True


class CameraDirector:
    """Presentation-only camera state; it never mutates simulation physics."""

    _PRESETS = {
        SimulationState.INITIALIZING: (138.0, -24.0, 1.82),
        SimulationState.HOME: (138.0, -24.0, 1.72),
        SimulationState.PRE_GRASP: (112.0, -22.0, 1.16),
        SimulationState.APPROACH: (154.0, -15.0, 1.00),
        SimulationState.ALIGN: (92.0, -8.0, 0.78),
        SimulationState.CLOSE: (82.0, -4.0, 0.64),
        SimulationState.LIFT: (122.0, -16.0, 0.96),
        SimulationState.VERIFY: (144.0, -22.0, 1.48),
        SimulationState.SUCCESS: (132.0, -18.0, 1.68),
        SimulationState.FAILED: (96.0, -10.0, 0.88),
    }

    def __init__(self, mode: CameraMode = CameraMode.AUTO_CINEMATIC) -> None:
        self._lock = threading.RLock()
        self.mode = mode
        self.azimuth = 138.0
        self.elevation = -24.0
        self.distance = 1.58
        self.lookat = np.array([0.0, 0.0, 0.90], dtype=np.float64)

    def set_mode(self, mode: CameraMode) -> None:
        with self._lock:
            self.mode = mode

    def manual_delta(self, *, rotate_x: float, rotate_y: float, pan_x: float, pan_y: float, zoom: float) -> None:
        with self._lock:
            self.mode = CameraMode.FREE_CAMERA
            self.azimuth += float(rotate_x) * 0.35
            self.elevation = float(np.clip(self.elevation + float(rotate_y) * 0.25, -80.0, 20.0))
            self.lookat[0] += float(pan_x) * 0.0015 * self.distance
            self.lookat[2] += float(pan_y) * 0.0015 * self.distance
            self.distance = float(np.clip(self.distance * math.exp(float(zoom) * 0.001), 0.42, 3.0))

    def camera(self, state: SimulationState, target: np.ndarray, eef: np.ndarray) -> mujoco.MjvCamera:
        with self._lock:
            if self.mode is CameraMode.AUTO_CINEMATIC:
                self.azimuth, self.elevation, self.distance = self._PRESETS.get(
                    state, self._PRESETS[SimulationState.HOME]
                )
                self.lookat = (
                    target.copy()
                    if state in {SimulationState.ALIGN, SimulationState.CLOSE, SimulationState.LIFT,
                                 SimulationState.VERIFY, SimulationState.SUCCESS, SimulationState.FAILED}
                    else (target + eef) / 2.0
                )
            elif self.mode is CameraMode.TECHNICAL:
                self.azimuth, self.elevation, self.distance = 135.0, -28.0, 1.55
                self.lookat = np.array([0.0, 0.0, 0.91], dtype=np.float64)
            elif self.mode is CameraMode.TARGET_FOLLOW:
                self.azimuth, self.elevation, self.distance = 132.0, -18.0, 1.05
                self.lookat = target.copy()
            camera = mujoco.MjvCamera()
            mujoco.mjv_defaultCamera(camera)
            camera.type = mujoco.mjtCamera.mjCAMERA_FREE
            camera.azimuth = self.azimuth
            camera.elevation = self.elevation
            camera.distance = self.distance
            camera.lookat[:] = self.lookat
            return camera


class RecordingPlaybackRenderer:
    """Restore recorded MuJoCo states for rendering without advancing physics."""

    def __init__(
        self,
        recording: SimulationRecording,
        camera_director: CameraDirector,
        *,
        width: int = 960,
        height: int = 540,
    ) -> None:
        self.recording = recording
        self.camera_director = camera_director
        self.width = width
        self.height = height
        self.model = mujoco.MjModel.from_xml_string(
            recording.model_xml, assets=recording.model_assets
        )
        if self.model.nq != recording.qpos.shape[1] or self.model.nv != recording.qvel.shape[1]:
            raise RuntimeError("recording is incompatible with its MuJoCo model")
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, height=height, width=width)
        self._target_body = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_BODY, "bottle_main"
        )
        self._eef_site = mujoco.mj_name2id(
            self.model, mujoco.mjtObj.mjOBJ_SITE, "gripper0_right_grip_site"
        )
        self._render_option = mujoco.MjvOption()
        mujoco.mjv_defaultOption(self._render_option)
        self._render_option.geomgroup[0] = 0
        self._render_option.geomgroup[1] = 1

    def close(self) -> None:
        self.renderer.close()

    def render_at(self, timestamp_s: float, *, technical_overlay: bool = True) -> tuple[bytes, dict[str, object]]:
        index = self.recording.index_at(timestamp_s)
        self.data.qpos[:] = self.recording.qpos[index]
        self.data.qvel[:] = self.recording.qvel[index]
        self.data.time = float(self.recording.timestamps[index])
        # mj_forward recomputes derived poses/contacts for rendering only. It
        # does not integrate the state and therefore cannot change the result.
        mujoco.mj_forward(self.model, self.data)
        state = SimulationState(self.recording.validation_states[index])
        target = self.data.xpos[self._target_body].copy()
        eef = self.data.site_xpos[self._eef_site].copy()
        camera = self.camera_director.camera(state, target, eef)
        self.renderer.update_scene(self.data, camera=camera, scene_option=self._render_option)
        if technical_overlay:
            self._add_contact_geometries(self.recording.contacts[index])
        rgb = self.renderer.render()
        rgb = self._decorate(rgb, index, state, technical_overlay)
        ok, encoded = cv2.imencode(
            ".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
            [cv2.IMWRITE_JPEG_QUALITY, 88],
        )
        if not ok:
            raise RuntimeError("MuJoCo playback frame encoding failed")
        telemetry = {
            "robot_state": state.value,
            "grasp_state": state.value,
            "target_id": (
                self.recording.request_metadata.get("simulation_attempt")
                or self.recording.request_metadata.get("grasp_plan", {})
            ).get("target_id"),
            "collision": bool(self.recording.collision_states[index]),
            "target_position_world": self.recording.target_poses[index, :3].tolist(),
            "target_velocity": self.recording.target_velocities[index].tolist(),
            "eef_position_world": self.recording.eef_positions[index].tolist(),
            "lift_height_m": float(self.recording.lift_heights[index]),
            "contact_count": len(self.recording.contacts[index]),
            "recording_timestamp_s": float(self.recording.timestamps[index]),
            "recording_index": index,
            "playback_source": "RECORDED_MUJOCO_STATE",
            "target_appearance": self.recording.request_metadata.get("target_appearance"),
        }
        return encoded.tobytes(), telemetry

    def _add_contact_geometries(self, contacts: tuple[ContactState, ...]) -> None:
        scene = self.renderer.scene
        for contact in contacts[:24]:
            if scene.ngeom >= scene.maxgeom:
                break
            mujoco.mjv_initGeom(
                scene.geoms[scene.ngeom],
                mujoco.mjtGeom.mjGEOM_SPHERE,
                np.array([0.008, 0.008, 0.008], dtype=np.float64),
                np.asarray(contact.position_world, dtype=np.float64),
                np.eye(3, dtype=np.float64).reshape(-1),
                np.array([1.0, 0.22, 0.12, 0.94], dtype=np.float32),
            )
            scene.ngeom += 1

    def _decorate(
        self,
        rgb: np.ndarray,
        index: int,
        state: SimulationState,
        technical_overlay: bool,
    ) -> np.ndarray:
        overlay = rgb.copy()
        cv2.rectangle(overlay, (12, 12), (min(rgb.shape[1] - 12, 510), 94), (3, 13, 23), -1)
        rgb = cv2.addWeighted(overlay, 0.74, rgb, 0.26, 0.0)
        cv2.putText(rgb, f"RECORDING PLAYBACK  {state.value}", (26, 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, (185, 232, 250), 1, cv2.LINE_AA)
        cv2.putText(
            rgb,
            f"t={self.recording.timestamps[index]:.3f}s  lift={self.recording.lift_heights[index]:.3f}m  "
            f"contacts={len(self.recording.contacts[index])}",
            (26, 61), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (120, 185, 214), 1, cv2.LINE_AA,
        )
        cv2.putText(
            rgb,
            "TECHNICAL OVERLAY · RECORDED STATE" if technical_overlay else "CINEMATIC · RECORDED STATE",
            (26, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (110, 235, 202), 1, cv2.LINE_AA,
        )
        if state is SimulationState.SUCCESS:
            cv2.rectangle(rgb, (3, 3), (rgb.shape[1] - 4, rgb.shape[0] - 4), (80, 245, 180), 5)
        elif state is SimulationState.FAILED:
            cv2.rectangle(rgb, (3, 3), (rgb.shape[1] - 4, rgb.shape[0] - 4), (244, 92, 88), 5)
        return rgb


class NativePandaValidation:
    """Position-actuated Panda with DLS IK keyframes and dynamic target contact."""

    _HOME_Q = np.array([0.0, -0.58, 0.0, -2.20, 0.0, 1.64, 0.78], dtype=np.float64)

    def __init__(
        self,
        request: ValidationRequest,
        camera_director: CameraDirector,
        config: NativePandaValidationConfig | None = None,
    ) -> None:
        self.request = request
        self.camera_director = camera_director
        self.config = config or NativePandaValidationConfig()
        appearance = request.target_appearance
        proxy_geometry = ProxyGeometry.BOX if appearance is None else appearance.proxy_geometry
        self.appearance_runtime_metadata = request.appearance_metadata()
        try:
            self.model_xml, self.model_assets = self._build_model(
                request,
                appearance=appearance,
                proxy_geometry=proxy_geometry,
                offscreen_width=self.config.width,
                offscreen_height=self.config.height,
            )
            self.model = mujoco.MjModel.from_xml_string(
                self.model_xml, assets=self.model_assets
            )
            if appearance is not None:
                self._verify_target_appearance_loaded(self.model, appearance)
                self.appearance_runtime_metadata = {
                    **appearance.public_metadata(),
                    "texture_status": "LOADED",
                    "appearance_status": "REAL_RGB",
                    "runtime_binding": "MUJOCO_TEXTURE_MATERIAL_VISUAL_GEOM",
                }
        except Exception as error:
            if appearance is None:
                raise
            self.appearance_runtime_metadata = {
                **appearance.public_metadata(),
                "texture_status": "FAILED",
                "appearance_status": "APPEARANCE_FALLBACK",
                "failure_reason": f"{type(error).__name__}: {str(error) or 'MuJoCo texture load failed'}",
                "runtime_binding": "FALLBACK_PROXY_COLOR",
            }
            self.model_xml, self.model_assets = self._build_model(
                request,
                appearance=None,
                proxy_geometry=proxy_geometry,
                offscreen_width=self.config.width,
                offscreen_height=self.config.height,
            )
            self.model = mujoco.MjModel.from_xml_string(self.model_xml)
        self.data = mujoco.MjData(self.model)
        self._arm_joint_ids = [mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, f"robot0_joint{i}") for i in range(1, 8)]
        self._arm_qpos = np.array([self.model.jnt_qposadr[j] for j in self._arm_joint_ids], dtype=np.int32)
        self._arm_dofs = np.array([self.model.jnt_dofadr[j] for j in self._arm_joint_ids], dtype=np.int32)
        self._eef_site = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_SITE, "gripper0_right_grip_site")
        self._target_body = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, "bottle_main")
        self._target_joint = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, "bottle_joint0")
        self._finger_joints = [
            mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, "gripper0_right_finger_joint1"),
            mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, "gripper0_right_finger_joint2"),
        ]
        self._render_option = mujoco.MjvOption()
        mujoco.mjv_defaultOption(self._render_option)
        self._render_option.geomgroup[0] = 0
        self._render_option.geomgroup[1] = 1
        self._initialize_data()
        self.recording: SimulationRecording | None = None
        self._recording_initial_z = float(self.data.xpos[self._target_body, 2])
        if self.config.recording_hz <= 0.0:
            raise ValueError("recording_hz must be positive")
        self._recording_period = 1.0 / self.config.recording_hz
        self._next_record_time = 0.0
        self._sample_step = 0
        self._sample_timestamps: list[float] = []
        self._sample_qpos: list[np.ndarray] = []
        self._sample_qvel: list[np.ndarray] = []
        self._sample_gripper: list[np.ndarray] = []
        self._sample_target_pose: list[np.ndarray] = []
        self._sample_target_velocity: list[np.ndarray] = []
        self._sample_eef: list[np.ndarray] = []
        self._sample_collision: list[bool] = []
        self._sample_lift: list[float] = []
        self._sample_states: list[str] = []
        self._sample_contacts: list[tuple[ContactState, ...]] = []
        self._events: list[RecordingEvent] = []
        self._last_target_gripper_contact = False

    def run(self, callback: FrameCallback, stop_event: threading.Event) -> ValidationResult:
        renderer: mujoco.Renderer | None = None
        initial_target_z = float(self.data.xpos[self._target_body, 2])
        invalid_collision = False
        close_executed = False
        lift_samples: list[float] = []
        completed = False
        result: ValidationResult | None = None
        try:
            renderer = mujoco.Renderer(self.model, height=self.config.height, width=self.config.width)
            pre_position = self.request.scene_transform.grasp_position_world - self.request.scene_transform.approach_world * 0.18
            approach_position = self.request.scene_transform.grasp_position_world - self.request.scene_transform.approach_world * 0.065
            grasp_position = self.request.scene_transform.grasp_position_world.copy()
            lift_position = grasp_position - self.request.scene_transform.approach_world * 0.13
            target_rotation = self._target_gripper_rotation()
            pre_q = self._solve_ik(pre_position, target_rotation, self._HOME_Q)
            approach_q = self._solve_ik(approach_position, target_rotation, pre_q)
            grasp_q = self._solve_ik(grasp_position, target_rotation, approach_q)
            lift_q = self._solve_ik(lift_position, target_rotation, grasp_q)

            phases = (
                (SimulationState.HOME, self._HOME_Q, self._HOME_Q, 0.65, 1.0),
                (SimulationState.PRE_GRASP, self._HOME_Q, pre_q, 1.05, 1.0),
                (SimulationState.APPROACH, pre_q, approach_q, 1.45, 1.0),
                (SimulationState.ALIGN, approach_q, grasp_q, 0.95, 1.0),
                (SimulationState.CLOSE, grasp_q, grasp_q, 1.05, 0.0),
                (SimulationState.LIFT, grasp_q, lift_q, 1.55, 0.0),
                (SimulationState.VERIFY, lift_q, lift_q, max(0.75, self.config.stable_window_s), 0.0),
            )
            self._events.append(RecordingEvent(float(self.data.time), "SIMULATION_STARTED", SimulationState.HOME.value))
            self._record_sample(SimulationState.HOME, force=True)
            aborted_on_collision = False
            for state, start_q, end_q, duration, gripper in phases:
                if stop_event.is_set():
                    raise RuntimeError("validation stopped")
                self._events.append(RecordingEvent(float(self.data.time), "PHASE_STARTED", state.value))
                if state is SimulationState.CLOSE:
                    close_executed = True
                phase_collision, samples = self._run_phase(
                    state, start_q, end_q, duration, gripper, renderer, callback, stop_event
                )
                invalid_collision = invalid_collision or phase_collision
                if state is SimulationState.VERIFY:
                    lift_samples.extend(samples)
                if phase_collision:
                    aborted_on_collision = True
                    self._events.append(RecordingEvent(
                        float(self.data.time),
                        SimulationFailureReason.COLLISION_ABORT.value,
                        state.value,
                    ))
                    break
            completed = not aborted_on_collision
            lift_height = float(self.data.xpos[self._target_body, 2] - initial_target_z)
            stable = bool(
                lift_samples
                and max(lift_samples) - min(lift_samples) <= 0.012
                and lift_height >= self.config.lift_height_m
            )
            reason = self._classify_failure(
                invalid_collision=invalid_collision,
                close_executed=close_executed,
                lift_height=lift_height,
                stable=stable,
            )
            final_state = SimulationState.SUCCESS if reason is None else SimulationState.FAILED
            result = ValidationResult(
                state=final_state,
                reason=reason,
                state_machine_complete=completed,
                invalid_table_collision=invalid_collision,
                gripper_close_executed=close_executed,
                lift_height_m=lift_height,
                stable_window_passed=stable,
            )
            self._events.append(RecordingEvent(float(self.data.time), "VALIDATION_RESULT", final_state.value))
            if reason is not None:
                self._events.append(RecordingEvent(float(self.data.time), reason, final_state.value))
            self._hold_final(final_state, renderer, callback, stop_event, result.public_metadata())
            self._record_sample(final_state, force=True)
            self._finalize_recording(result)
            return result
        except Exception as error:
            lift_height = float(self.data.xpos[self._target_body, 2] - initial_target_z)
            result = ValidationResult(
                state=SimulationState.FAILED,
                reason=SimulationFailureReason.EXECUTION_ERROR.value,
                state_machine_complete=completed,
                invalid_table_collision=invalid_collision,
                gripper_close_executed=close_executed,
                lift_height_m=lift_height,
                stable_window_passed=False,
                failure_detail=str(error) or "State Error",
            )
            self._events.append(RecordingEvent(float(self.data.time), "VALIDATION_RESULT", SimulationState.FAILED.value))
            self._events.append(
                RecordingEvent(
                    float(self.data.time),
                    SimulationFailureReason.EXECUTION_ERROR.value,
                    SimulationState.FAILED.value,
                )
            )
            if renderer is not None:
                self._hold_final(SimulationState.FAILED, renderer, callback, stop_event, result.public_metadata())
            self._record_sample(SimulationState.FAILED, force=True)
            self._finalize_recording(result)
            return result
        finally:
            if renderer is not None:
                renderer.close()

    def _run_phase(
        self,
        state: SimulationState,
        start_q: np.ndarray,
        end_q: np.ndarray,
        duration: float,
        gripper: float,
        renderer: mujoco.Renderer,
        callback: FrameCallback,
        stop_event: threading.Event,
    ) -> tuple[bool, list[float]]:
        steps = max(1, round(duration / self.model.opt.timestep))
        render_stride = max(1, round(1.0 / (self.config.render_fps * self.model.opt.timestep)))
        invalid_collision = False
        target_samples: list[float] = []
        next_frame_time = time.monotonic()
        for step in range(steps):
            if stop_event.is_set():
                raise RuntimeError("validation stopped")
            phase = step / max(steps - 1, 1)
            eased = self._ease(state, phase)
            self.data.ctrl[:7] = start_q + (end_q - start_q) * eased
            self.data.ctrl[7] = 0.5 * self.request.grasp_plan.gripper_width * gripper
            self.data.ctrl[8] = -0.5 * self.request.grasp_plan.gripper_width * gripper
            # Feed-forward the model bias on the seven arm DoFs. Position
            # actuators remain the controller; this only prevents gravity from
            # creating a persistent tracking offset during slow showcase moves.
            self.data.qfrc_applied[self._arm_dofs] = self.data.qfrc_bias[self._arm_dofs]
            mujoco.mj_step(self.model, self.data)
            self._sample_step += 1
            self._record_sample(state)
            collision_now = self._has_invalid_table_collision()
            invalid_collision = invalid_collision or collision_now
            if state is SimulationState.VERIFY:
                target_samples.append(float(self.data.xpos[self._target_body, 2]))
            if step % render_stride == 0 or step == steps - 1 or collision_now:
                callback(state, self._render(renderer, state), self._telemetry(state))
                if self.config.realtime_playback:
                    next_frame_time += 1.0 / self.config.render_fps
                    remaining = next_frame_time - time.monotonic()
                    if remaining > 0.0:
                        time.sleep(remaining)
            if collision_now:
                return True, target_samples
        return invalid_collision, target_samples

    def _classify_failure(
        self,
        *,
        invalid_collision: bool,
        close_executed: bool,
        lift_height: float,
        stable: bool,
    ) -> str | None:
        """Classify observed dynamics without consulting the planning verdict."""

        if invalid_collision:
            return SimulationFailureReason.COLLISION_ABORT.value
        if not close_executed:
            return SimulationFailureReason.EXECUTION_ERROR.value
        contact_samples = [
            self._has_target_gripper_contact(contacts)
            for state, contacts in zip(self._sample_states, self._sample_contacts, strict=True)
            if state in {
                SimulationState.CLOSE.value,
                SimulationState.LIFT.value,
                SimulationState.VERIFY.value,
            }
        ]
        if not any(contact_samples):
            return SimulationFailureReason.NO_CONTACT.value
        max_lift = max(self._sample_lift, default=lift_height)
        if max_lift >= self.config.lift_height_m and lift_height < self.config.lift_height_m:
            return SimulationFailureReason.SLIP.value
        if contact_samples and not contact_samples[-1]:
            return SimulationFailureReason.CONTACT_LOSS.value
        if lift_height < self.config.lift_height_m:
            return SimulationFailureReason.NO_LIFT.value
        if not stable:
            return SimulationFailureReason.UNSTABLE_GRASP.value
        return None

    @staticmethod
    def _has_target_gripper_contact(contacts: tuple[ContactState, ...]) -> bool:
        for contact in contacts:
            names = (contact.geom1.lower(), contact.geom2.lower())
            target = any(name.startswith("bottle_") for name in names)
            gripper = any(name.startswith("gripper0_") for name in names)
            if target and gripper:
                return True
        return False

    def _hold_final(
        self,
        state: SimulationState,
        renderer: mujoco.Renderer,
        callback: FrameCallback,
        stop_event: threading.Event,
        result: dict[str, object],
    ) -> None:
        frames = max(1, int(self.config.render_fps * 1.0))
        steps_per_frame = max(1, round(1.0 / (self.config.render_fps * self.model.opt.timestep)))
        next_frame_time = time.monotonic()
        for _ in range(frames):
            if stop_event.is_set():
                return
            for _ in range(steps_per_frame):
                self.data.qfrc_applied[self._arm_dofs] = self.data.qfrc_bias[self._arm_dofs]
                mujoco.mj_step(self.model, self.data)
                self._sample_step += 1
                self._record_sample(state)
            callback(
                state,
                self._render(renderer, state, result=result),
                {**self._telemetry(state), **result},
            )
            if self.config.realtime_playback:
                next_frame_time += 1.0 / self.config.render_fps
                remaining = next_frame_time - time.monotonic()
                if remaining > 0.0:
                    time.sleep(remaining)

    def _render(
        self,
        renderer: mujoco.Renderer,
        state: SimulationState,
        *,
        result: dict[str, object] | None = None,
    ) -> bytes:
        target = self.data.xpos[self._target_body].copy()
        eef = self.data.site_xpos[self._eef_site].copy()
        camera = self.camera_director.camera(state, target, eef)
        renderer.update_scene(self.data, camera=camera, scene_option=self._render_option)
        rgb = renderer.render()
        overlay = rgb.copy()
        cv2.rectangle(overlay, (12, 12), (min(rgb.shape[1] - 12, 390), 74), (3, 13, 23), -1)
        rgb = cv2.addWeighted(overlay, 0.74, rgb, 0.26, 0.0)
        cv2.putText(
            rgb,
            f"PANDA DYNAMIC VALIDATION  {state.value}",
            (26, 38),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (185, 232, 250),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            rgb,
            f"SCENARIO  {self.request.scenario.value}",
            (26, 61),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.40,
            (120, 185, 214),
            1,
            cv2.LINE_AA,
        )
        # The border and final reason are presentation-only; the result comes
        # from simulated contact, lift height, and the stability window.
        if state is SimulationState.SUCCESS:
            cv2.rectangle(rgb, (3, 3), (rgb.shape[1] - 4, rgb.shape[0] - 4), (80, 245, 180), 5)
        elif state is SimulationState.FAILED:
            cv2.rectangle(rgb, (3, 3), (rgb.shape[1] - 4, rgb.shape[0] - 4), (244, 92, 88), 5)
        if result is not None and state in {SimulationState.SUCCESS, SimulationState.FAILED}:
            label = (
                "PHYSICS SUCCESS"
                if state is SimulationState.SUCCESS
                else f"PHYSICS FAILURE  {result.get('reason') or 'STATE ERROR'}"
            )
            color = (92, 248, 186) if state is SimulationState.SUCCESS else (255, 122, 114)
            cv2.putText(
                rgb,
                label,
                (26, rgb.shape[0] - 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.66,
                color,
                2,
                cv2.LINE_AA,
            )
        ok, encoded = cv2.imencode(
            ".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88]
        )
        if not ok:
            raise RuntimeError("MuJoCo render frame encoding failed")
        return encoded.tobytes()

    def _telemetry(self, state: SimulationState) -> dict[str, object]:
        return {
            "robot_state": state.value,
            "grasp_state": state.value,
            "target_id": self.request.grasp_plan.target_id,
            "scenario": self.request.scenario.value,
            "target_offset_world": self.request.scene_transform.target_offset_world.tolist(),
            "collision": self._has_invalid_table_collision(),
            "target_position_world": self.data.xpos[self._target_body].tolist(),
            "eef_position_world": self.data.site_xpos[self._eef_site].tolist(),
            "target_appearance": dict(self.appearance_runtime_metadata),
        }

    def _record_sample(self, state: SimulationState, *, force: bool = False) -> None:
        if not force and float(self.data.time) + 1e-12 < self._next_record_time:
            return
        timestamp = float(self.data.time)
        if self._sample_timestamps and np.isclose(timestamp, self._sample_timestamps[-1], atol=1e-12):
            if not force:
                return
            # Preserve one state per timestamp while allowing the terminal
            # validation label to replace the last physical sample.
            self._sample_states[-1] = state.value
            self._sample_collision[-1] = self._has_invalid_table_collision()
            contacts = self._contact_states()
            self._sample_contacts[-1] = contacts
            self._record_contact_transition(timestamp, state, contacts)
            return
        contacts = self._contact_states()
        target_quat = self.data.xquat[self._target_body].copy()
        self._sample_timestamps.append(timestamp)
        self._sample_qpos.append(self.data.qpos.copy())
        self._sample_qvel.append(self.data.qvel.copy())
        self._sample_gripper.append(
            np.asarray(
                [self.data.qpos[self.model.jnt_qposadr[joint]] for joint in self._finger_joints],
                dtype=np.float64,
            )
        )
        self._sample_target_pose.append(
            np.concatenate((self.data.xpos[self._target_body].copy(), target_quat))
        )
        self._sample_target_velocity.append(self.data.cvel[self._target_body].copy())
        self._sample_eef.append(self.data.site_xpos[self._eef_site].copy())
        self._sample_collision.append(self._has_invalid_table_collision())
        self._sample_lift.append(float(self.data.xpos[self._target_body, 2] - self._recording_initial_z))
        self._sample_states.append(state.value)
        self._sample_contacts.append(contacts)
        self._record_contact_transition(timestamp, state, contacts)
        while self._next_record_time <= timestamp + 1e-12:
            self._next_record_time += self._recording_period

    def _contact_states(self) -> tuple[ContactState, ...]:
        contacts: list[ContactState] = []
        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            first = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom1) or ""
            second = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom2) or ""
            frame = np.asarray(contact.frame, dtype=np.float64).reshape(3, 3)
            contacts.append(
                ContactState(
                    tuple(float(value) for value in contact.pos),
                    tuple(float(value) for value in frame[0]),
                    first,
                    second,
                    float(contact.dist),
                )
            )
        return tuple(contacts)

    def _record_contact_transition(
        self,
        timestamp: float,
        state: SimulationState,
        contacts: tuple[ContactState, ...],
    ) -> None:
        current = self._has_target_gripper_contact(contacts)
        if current and not self._last_target_gripper_contact:
            self._events.append(RecordingEvent(timestamp, "CONTACT_ESTABLISHED", state.value))
        elif not current and self._last_target_gripper_contact:
            self._events.append(RecordingEvent(timestamp, "CONTACT_LOST", state.value))
        self._last_target_gripper_contact = current

    def _finalize_recording(self, result: ValidationResult) -> None:
        if self.recording is not None:
            return
        recording_id = f"rec-{uuid.uuid4().hex[:16]}"
        run_id = f"run-{uuid.uuid4().hex[:16]}"
        request_metadata = self.request.public_metadata()
        request_metadata["target_appearance"] = dict(self.appearance_runtime_metadata)
        self.recording = SimulationRecording(
            recording_id=recording_id,
            run_id=run_id,
            created_at=utc_timestamp(),
            sample_hz=float(self.config.recording_hz),
            timestamps=np.asarray(self._sample_timestamps, dtype=np.float64),
            qpos=np.asarray(self._sample_qpos, dtype=np.float64),
            qvel=np.asarray(self._sample_qvel, dtype=np.float64),
            gripper_states=np.asarray(self._sample_gripper, dtype=np.float64),
            target_poses=np.asarray(self._sample_target_pose, dtype=np.float64),
            target_velocities=np.asarray(self._sample_target_velocity, dtype=np.float64),
            eef_positions=np.asarray(self._sample_eef, dtype=np.float64),
            collision_states=np.asarray(self._sample_collision, dtype=np.bool_),
            lift_heights=np.asarray(self._sample_lift, dtype=np.float64),
            validation_states=tuple(self._sample_states),
            contacts=tuple(self._sample_contacts),
            events=tuple(self._events),
            result=result,
            request_metadata=request_metadata,
            compatibility={
                "mujoco_version": mujoco.__version__,
                "model_sha256": hashlib.sha256(self.model_xml.encode("utf-8")).hexdigest(),
                "asset_sha256": {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in self.model_assets.items()
                },
                "nq": int(self.model.nq),
                "nv": int(self.model.nv),
            },
            model_xml=self.model_xml,
            model_assets=self.model_assets,
        )

    def _solve_ik(self, target_position: np.ndarray, target_rotation: np.ndarray, seed_q: np.ndarray) -> np.ndarray:
        ik_data = mujoco.MjData(self.model)
        ik_data.qpos[:] = self.data.qpos
        ik_data.qpos[self._arm_qpos] = seed_q
        jac_pos = np.zeros((3, self.model.nv), dtype=np.float64)
        jac_rot = np.zeros((3, self.model.nv), dtype=np.float64)
        for _ in range(320):
            mujoco.mj_forward(self.model, ik_data)
            current_position = ik_data.site_xpos[self._eef_site]
            current_rotation = ik_data.site_xmat[self._eef_site].reshape(3, 3)
            position_error = target_position - current_position
            rotation_error = 0.5 * sum(
                np.cross(current_rotation[:, axis], target_rotation[:, axis]) for axis in range(3)
            )
            if np.linalg.norm(position_error) < 8e-4 and np.linalg.norm(rotation_error) < 8e-3:
                return ik_data.qpos[self._arm_qpos].copy()
            jac_pos.fill(0.0)
            jac_rot.fill(0.0)
            mujoco.mj_jacSite(self.model, ik_data, jac_pos, jac_rot, self._eef_site)
            jacobian = np.vstack((jac_pos[:, self._arm_dofs], 0.45 * jac_rot[:, self._arm_dofs]))
            error = np.concatenate((position_error, 0.45 * rotation_error))
            damping = 0.035
            delta = jacobian.T @ np.linalg.solve(
                jacobian @ jacobian.T + damping * damping * np.eye(6), error
            )
            max_delta = float(np.max(np.abs(delta)))
            if max_delta > 0.08:
                delta *= 0.08 / max_delta
            ik_data.qpos[self._arm_qpos] += delta
            for joint_id, qpos_address in zip(self._arm_joint_ids, self._arm_qpos, strict=True):
                if self.model.jnt_limited[joint_id]:
                    low, high = self.model.jnt_range[joint_id]
                    ik_data.qpos[qpos_address] = np.clip(ik_data.qpos[qpos_address], low + 1e-4, high - 1e-4)
        raise RuntimeError("DLS IK could not reach the normalized validation pose")

    def _target_gripper_rotation(self) -> np.ndarray:
        closing = self.request.scene_transform.closing_world
        finger = np.array([closing[1], -closing[0], 0.0], dtype=np.float64)
        approach = self.request.scene_transform.approach_world
        rotation = np.column_stack((closing, finger, approach))
        if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6):
            raise RuntimeError("validation grasp rotation is not right-handed")
        return rotation

    def _initialize_data(self) -> None:
        self.data.qpos[self._arm_qpos] = self._HOME_Q
        self.data.qpos[self.model.jnt_qposadr[self._finger_joints[0]]] = 0.04
        self.data.qpos[self.model.jnt_qposadr[self._finger_joints[1]]] = -0.04
        target_qpos = self.model.jnt_qposadr[self._target_joint]
        transform = self.request.scene_transform
        self.data.qpos[target_qpos : target_qpos + 3] = transform.target_position_world
        half_yaw = transform.target_yaw_rad / 2.0
        self.data.qpos[target_qpos + 3 : target_qpos + 7] = [math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw)]
        self.data.ctrl[:7] = self._HOME_Q
        self.data.ctrl[7:] = [0.04, -0.04]
        mujoco.mj_forward(self.model, self.data)

    def _has_invalid_table_collision(self) -> bool:
        for index in range(self.data.ncon):
            contact = self.data.contact[index]
            first = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom1) or ""
            second = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, contact.geom2) or ""
            names = (first.lower(), second.lower())
            table = any("table_collision" in name for name in names)
            robot = any(name.startswith(("robot0_", "gripper0_")) for name in names)
            target = any(name.startswith("bottle_") for name in names)
            if table and robot and not target:
                return True
        return False

    @staticmethod
    def _ease(state: SimulationState, value: float) -> float:
        if state in {SimulationState.APPROACH, SimulationState.ALIGN, SimulationState.CLOSE}:
            return value * value * value * (value * (value * 6.0 - 15.0) + 10.0)
        if state is SimulationState.LIFT:
            return value * value * (3.0 - 2.0 * value)
        return value * value * (3.0 - 2.0 * value)

    @classmethod
    def _build_model(
        cls,
        request: ValidationRequest,
        *,
        appearance: TargetAppearance | None,
        proxy_geometry: ProxyGeometry,
        offscreen_width: int,
        offscreen_height: int,
    ) -> tuple[str, dict[str, bytes]]:
        environment = BottleLift(
            robots="Panda",
            has_renderer=False,
            has_offscreen_renderer=False,
            use_camera_obs=False,
            hard_reset=False,
        )
        try:
            root = ET.fromstring(environment.model.get_xml())
        finally:
            environment.close()
        visual = root.find("visual")
        if visual is None:
            visual = ET.SubElement(root, "visual")
        global_visual = visual.find("global")
        if global_visual is None:
            global_visual = ET.SubElement(visual, "global")
        global_visual.attrib["offwidth"] = str(offscreen_width)
        global_visual.attrib["offheight"] = str(offscreen_height)
        actuator = root.find("actuator")
        if actuator is None:
            raise RuntimeError("Panda model is missing actuators")
        for element in list(actuator)[:7]:
            element.tag = "position"
            element.attrib.pop("gear", None)
            element.attrib.pop("ctrlrange", None)
            element.attrib.pop("ctrllimited", None)
            element.attrib["kp"] = "420"
            element.attrib["kv"] = "42"
            element.attrib["forcelimited"] = "true"
            original_range = "-87 87" if element.attrib.get("joint") not in {"robot0_joint6", "robot0_joint7"} else "-15 15"
            element.attrib["forcerange"] = original_range
        target = root.find(".//body[@name='bottle_main']")
        if target is None:
            raise RuntimeError("Panda validation model is missing target body")
        for child in list(target):
            if child.tag in {"geom", "site"}:
                target.remove(child)
        extents = request.scene_transform.target_extents_world
        half = extents / 2.0
        ET.SubElement(
            target,
            "geom",
            {
                "name": "bottle_target_collision",
                **cls._target_proxy_attributes(half, proxy_geometry, scale=1.0),
                "density": "220",
                "friction": "1.35 0.08 0.002",
                "solref": "0.008 1",
                "solimp": "0.95 0.99 0.001",
                "group": "0",
                # Physics remains a simple proxy with the existing density,
                # friction and contact parameters. It is transparent only so
                # the separate appearance shell can be rendered cleanly.
                "rgba": "0 0 0 0",
            },
        )
        visual_attributes = cls._target_visual_attributes(
            half, appearance, proxy_geometry
        )
        ET.SubElement(
            target,
            "geom",
            {
                "name": "bottle_target_visual",
                "mass": "0.00000001",
                "contype": "0",
                "conaffinity": "0",
                "group": "1",
                **visual_attributes,
            },
        )
        model_assets: dict[str, bytes] = {}
        if appearance is not None:
            asset = root.find("asset")
            if asset is None:
                asset = ET.SubElement(root, "asset")
            ET.SubElement(
                asset,
                "texture",
                {
                    "name": "target_appearance_texture",
                    "type": "2d",
                    "file": TARGET_TEXTURE_ASSET_NAME,
                },
            )
            ET.SubElement(
                asset,
                "material",
                {
                    "name": "target_appearance_material",
                    "texture": "target_appearance_texture",
                    "texuniform": (
                        "false" if proxy_geometry is ProxyGeometry.BOX else "true"
                    ),
                    "texrepeat": "1 1",
                    "rgba": "1 1 1 1",
                    "specular": "0.16",
                    "shininess": "0.24",
                },
            )
            model_assets = appearance.model_assets()
            if proxy_geometry is ProxyGeometry.BOX:
                ET.SubElement(
                    asset,
                    "mesh",
                    {
                        "name": "target_box_appearance_mesh",
                        "file": TARGET_BOX_VISUAL_MESH_ASSET_NAME,
                    },
                )
                model_assets[TARGET_BOX_VISUAL_MESH_ASSET_NAME] = (
                    cls._box_visual_mesh_obj(half * 0.992)
                )
        worldbody = root.find("worldbody")
        if worldbody is None:
            raise RuntimeError("Panda model is missing worldbody")
        ET.SubElement(worldbody, "light", {"name": "cinematic_key", "pos": "-0.2 -0.7 2.3", "dir": "0.15 0.35 -1", "diffuse": "0.82 0.88 1", "specular": "0.45 0.55 0.75", "directional": "true", "castshadow": "true"})
        ET.SubElement(worldbody, "light", {"name": "cinematic_fill", "pos": "0.9 0.4 1.5", "dir": "-0.6 -0.2 -0.7", "diffuse": "0.34 0.48 0.62", "specular": "0.18 0.25 0.34", "directional": "true"})
        cls._add_showcase_geometry(worldbody, request)
        table_body = root.find(".//body[@name='table']")
        if table_body is not None:
            for geom in table_body.findall(".//geom"):
                if geom.attrib.get("group") != "0":
                    geom.attrib.pop("material", None)
                    geom.attrib["rgba"] = "0.075 0.09 0.115 1"
        for geom in root.findall(".//geom"):
            name = geom.attrib.get("name", "").lower()
            if "floor" in name and geom.attrib.get("group") != "0":
                geom.attrib.pop("material", None)
                geom.attrib["rgba"] = "0.025 0.035 0.05 1"
        for texture in root.findall(".//texture"):
            if texture.attrib.get("type") == "skybox":
                texture.attrib["rgb1"] = "0.015 0.025 0.045"
                texture.attrib["rgb2"] = "0.07 0.10 0.14"
        return ET.tostring(root, encoding="unicode"), model_assets

    @staticmethod
    def _target_visual_attributes(
        half: np.ndarray,
        appearance: TargetAppearance | None,
        geometry: ProxyGeometry | None = None,
    ) -> dict[str, str]:
        """Build a collision-disabled shell that stays inside the physics proxy."""

        geometry = geometry or (
            ProxyGeometry.BOX if appearance is None else appearance.proxy_geometry
        )
        common = {
            "rgba": "0.05 0.82 1.0 0.96" if appearance is None else "1 1 1 1",
            "material": "" if appearance is None else "target_appearance_material",
        }
        if appearance is not None and geometry is ProxyGeometry.BOX:
            return {
                **common,
                "type": "mesh",
                "mesh": "target_box_appearance_mesh",
            }
        return {
            **common,
            **NativePandaValidation._target_proxy_attributes(half, geometry, scale=0.992),
        }

    @staticmethod
    def _target_proxy_attributes(
        half: np.ndarray,
        geometry: ProxyGeometry,
        *,
        scale: float,
    ) -> dict[str, str]:
        """Map extents to one low-complexity proxy used by physics or rendering."""

        padded = np.maximum(np.asarray(half, dtype=np.float64) * scale, 0.0015)
        if geometry is ProxyGeometry.BOX:
            return {
                "type": "box",
                "size": " ".join(f"{value:.8f}" for value in padded),
            }
        if geometry is ProxyGeometry.CYLINDER:
            radius = max(min(float(padded[0]), float(padded[1])), 0.0015)
            return {
                "type": "cylinder",
                "size": f"{radius:.8f} {float(padded[2]):.8f}",
            }
        if geometry is ProxyGeometry.CAPSULE:
            axis = int(np.argmax(padded))
            other = [index for index in range(3) if index != axis]
            radius = max(min(float(padded[other[0]]), float(padded[other[1]])), 0.0015)
            half_length = max(float(padded[axis]) - radius, 0.0015)
            attributes = {
                "type": "capsule",
                "size": f"{radius:.8f} {half_length:.8f}",
            }
            if axis == 0:
                attributes["quat"] = "0.70710678 0 0.70710678 0"
            elif axis == 1:
                attributes["quat"] = "0.70710678 -0.70710678 0 0"
            return attributes
        # Ellipsoid is also the stable visual fallback for an irregular mask;
        # v0.7 does not invent a high-resolution mesh from monocular RGB.
        return {
            "type": "ellipsoid",
            "size": " ".join(f"{value:.8f}" for value in padded),
        }

    @staticmethod
    def _box_visual_mesh_obj(half: np.ndarray) -> bytes:
        """Return a six-face box whose top/front has explicit full-image UVs.

        All other faces sample the texture's median-colour border. This makes
        packaging artwork visible on the view-facing face without projecting
        the phone background or inventing unseen surfaces.
        """

        x, y, z = (float(value) for value in np.asarray(half, dtype=np.float64))
        vertices = (
            (-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
            (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z),
        )
        lines = [
            *(f"v {vx:.9f} {vy:.9f} {vz:.9f}" for vx, vy, vz in vertices),
            "vt 0 0", "vt 1 0", "vt 1 1", "vt 0 1", "vt 0.01 0.01",
            # Positive Z is the normalized scene's visible/front face.
            "f 5/1 6/2 7/3", "f 5/1 7/3 8/4",
            # Back and sides use the guaranteed median-colour texture border.
            "f 1/5 3/5 2/5", "f 1/5 4/5 3/5",
            "f 1/5 2/5 6/5", "f 1/5 6/5 5/5",
            "f 2/5 3/5 7/5", "f 2/5 7/5 6/5",
            "f 3/5 4/5 8/5", "f 3/5 8/5 7/5",
            "f 4/5 1/5 5/5", "f 4/5 5/5 8/5",
        ]
        return ("\n".join(lines) + "\n").encode("ascii")

    @staticmethod
    def _verify_target_appearance_loaded(
        model: mujoco.MjModel, appearance: TargetAppearance
    ) -> None:
        texture_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_TEXTURE, "target_appearance_texture"
        )
        material_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_MATERIAL, "target_appearance_material"
        )
        visual_id = mujoco.mj_name2id(
            model, mujoco.mjtObj.mjOBJ_GEOM, "bottle_target_visual"
        )
        if min(texture_id, material_id, visual_id) < 0:
            raise RuntimeError("target appearance asset binding is incomplete")
        if int(model.geom_matid[visual_id]) != material_id:
            raise RuntimeError("target visual geom is not bound to appearance material")
        if int(model.tex_width[texture_id]) < 1 or int(model.tex_height[texture_id]) < 1:
            raise RuntimeError("target appearance texture has invalid dimensions")
        if appearance.proxy_geometry is ProxyGeometry.BOX:
            if int(model.geom_type[visual_id]) != int(mujoco.mjtGeom.mjGEOM_MESH):
                raise RuntimeError("box appearance must use an explicit-UV visual mesh")
            mesh_id = int(model.geom_dataid[visual_id])
            if mesh_id < 0 or int(model.mesh_texcoordnum[mesh_id]) < 4:
                raise RuntimeError("box appearance mesh has no usable UV coordinates")

    @staticmethod
    def _add_showcase_geometry(worldbody: ET.Element, request: ValidationRequest) -> None:
        transform = request.scene_transform
        grasp = transform.grasp_position_world
        pre = grasp - transform.approach_world * 0.18
        yaw_quat = f"{math.cos(transform.target_yaw_rad / 2):.8f} 0 0 {math.sin(transform.target_yaw_rad / 2):.8f}"
        overlay = ET.SubElement(worldbody, "body", {"name": "showcase_overlay"})
        ET.SubElement(overlay, "geom", {"name": "grasp_point_visual", "type": "sphere", "pos": " ".join(map(str, grasp)), "size": "0.012", "rgba": "1 0.72 0.08 0.95", "contype": "0", "conaffinity": "0", "group": "1"})
        midpoint = (grasp + pre) / 2.0
        ET.SubElement(overlay, "geom", {"name": "approach_vector_visual", "type": "cylinder", "pos": " ".join(map(str, midpoint)), "size": f"0.004 {np.linalg.norm(pre-grasp)/2:.6f}", "rgba": "0.15 0.92 1 0.72", "contype": "0", "conaffinity": "0", "group": "1"})
        for index, position in enumerate(np.linspace(pre, grasp, 11)):
            ET.SubElement(overlay, "geom", {"name": f"eef_trajectory_{index}", "type": "sphere", "pos": " ".join(map(str, position)), "size": "0.004", "rgba": f"0.10 0.72 1 {0.18 + index * 0.045:.3f}", "contype": "0", "conaffinity": "0", "group": "1"})
        for prefix, position, alpha in (("pre", pre, "0.22"), ("final", grasp, "0.34")):
            ghost = ET.SubElement(overlay, "body", {"name": f"ghost_gripper_{prefix}", "pos": " ".join(map(str, position)), "quat": yaw_quat})
            ET.SubElement(ghost, "geom", {"type": "box", "pos": "0 0 0.035", "size": "0.048 0.012 0.014", "rgba": f"0.18 0.92 1 {alpha}", "contype": "0", "conaffinity": "0", "group": "1"})
            half_width = request.grasp_plan.gripper_width / 2.0
            for sign in (-1.0, 1.0):
                ET.SubElement(ghost, "geom", {"type": "box", "pos": f"{sign * half_width:.6f} 0 -0.005", "size": "0.006 0.012 0.055", "rgba": f"0.18 0.92 1 {alpha}", "contype": "0", "conaffinity": "0", "group": "1"})
