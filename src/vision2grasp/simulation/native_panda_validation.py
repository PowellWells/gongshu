"""Continuous native-MuJoCo Panda validation driven only by ValidationRequest."""

from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Callable
from xml.etree import ElementTree as ET

import cv2
import mujoco
import numpy as np

from vision2grasp.simulation.bottle_lift import BottleLift

from .validation_contracts import (
    CameraMode,
    SimulationState,
    ValidationRequest,
    ValidationResult,
)


FrameCallback = Callable[[SimulationState, bytes, dict[str, object]], None]


@dataclass(frozen=True, slots=True)
class NativePandaValidationConfig:
    width: int = 960
    height: int = 540
    render_fps: int = 24
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

    def __init__(self, mode: CameraMode = CameraMode.CINEMATIC) -> None:
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
            self.mode = CameraMode.MANUAL
            self.azimuth += float(rotate_x) * 0.35
            self.elevation = float(np.clip(self.elevation + float(rotate_y) * 0.25, -80.0, 20.0))
            self.lookat[0] += float(pan_x) * 0.0015 * self.distance
            self.lookat[2] += float(pan_y) * 0.0015 * self.distance
            self.distance = float(np.clip(self.distance * math.exp(float(zoom) * 0.001), 0.42, 3.0))

    def camera(self, state: SimulationState, target: np.ndarray, eef: np.ndarray) -> mujoco.MjvCamera:
        with self._lock:
            if self.mode is CameraMode.CINEMATIC:
                desired = self._PRESETS.get(state, self._PRESETS[SimulationState.HOME])
                alpha = 0.075 if state not in {SimulationState.CLOSE, SimulationState.SUCCESS} else 0.11
                self.azimuth += (desired[0] - self.azimuth) * alpha
                self.elevation += (desired[1] - self.elevation) * alpha
                self.distance += (desired[2] - self.distance) * alpha
                focus = target if state in {SimulationState.ALIGN, SimulationState.CLOSE, SimulationState.FAILED} else (target + eef) / 2.0
                if state in {SimulationState.SUCCESS, SimulationState.VERIFY}:
                    focus = target
                self.lookat += (focus - self.lookat) * 0.10
            elif self.mode is CameraMode.AUTO_FOLLOW:
                self.lookat += (((target + eef) / 2.0) - self.lookat) * 0.12
                self.distance += (1.28 - self.distance) * 0.08
                self.azimuth += (138.0 - self.azimuth) * 0.06
                self.elevation += (-24.0 - self.elevation) * 0.06
            camera = mujoco.MjvCamera()
            mujoco.mjv_defaultCamera(camera)
            camera.type = mujoco.mjtCamera.mjCAMERA_FREE
            camera.azimuth = self.azimuth
            camera.elevation = self.elevation
            camera.distance = self.distance
            camera.lookat[:] = self.lookat
            return camera


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
        self.model = self._build_model(
            request,
            offscreen_width=self.config.width,
            offscreen_height=self.config.height,
        )
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

    def run(self, callback: FrameCallback, stop_event: threading.Event) -> ValidationResult:
        renderer: mujoco.Renderer | None = None
        initial_target_z = float(self.data.xpos[self._target_body, 2])
        invalid_collision = False
        close_executed = False
        lift_samples: list[float] = []
        completed = False
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
            for state, start_q, end_q, duration, gripper in phases:
                if stop_event.is_set():
                    raise RuntimeError("validation stopped")
                if state is SimulationState.CLOSE:
                    close_executed = True
                phase_collision, samples = self._run_phase(
                    state, start_q, end_q, duration, gripper, renderer, callback, stop_event
                )
                invalid_collision = invalid_collision or phase_collision
                if state is SimulationState.VERIFY:
                    lift_samples.extend(samples)
            completed = True
            lift_height = float(self.data.xpos[self._target_body, 2] - initial_target_z)
            stable = bool(
                lift_samples
                and max(lift_samples) - min(lift_samples) <= 0.012
                and lift_height >= self.config.lift_height_m
            )
            if invalid_collision:
                final_state, reason = SimulationState.FAILED, "Collision"
            elif not close_executed:
                final_state, reason = SimulationState.FAILED, "State Error"
            elif lift_height < self.config.lift_height_m:
                final_state, reason = SimulationState.FAILED, "Lift Failed"
            elif not stable:
                final_state, reason = SimulationState.FAILED, "Stability Failed"
            else:
                final_state, reason = SimulationState.SUCCESS, None
            result = ValidationResult(
                state=final_state,
                reason=reason,
                state_machine_complete=completed,
                invalid_table_collision=invalid_collision,
                gripper_close_executed=close_executed,
                lift_height_m=lift_height,
                stable_window_passed=stable,
            )
            self._hold_final(final_state, renderer, callback, stop_event, result.public_metadata())
            return result
        except Exception as error:
            lift_height = float(self.data.xpos[self._target_body, 2] - initial_target_z)
            result = ValidationResult(
                state=SimulationState.FAILED,
                reason=str(error) or "State Error",
                state_machine_complete=completed,
                invalid_table_collision=invalid_collision,
                gripper_close_executed=close_executed,
                lift_height_m=lift_height,
                stable_window_passed=False,
            )
            if renderer is not None:
                self._hold_final(SimulationState.FAILED, renderer, callback, stop_event, result.public_metadata())
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
            invalid_collision = invalid_collision or self._has_invalid_table_collision()
            if state is SimulationState.VERIFY:
                target_samples.append(float(self.data.xpos[self._target_body, 2]))
            if step % render_stride == 0 or step == steps - 1:
                callback(state, self._render(renderer, state), self._telemetry(state))
                if self.config.realtime_playback:
                    next_frame_time += 1.0 / self.config.render_fps
                    remaining = next_frame_time - time.monotonic()
                    if remaining > 0.0:
                        time.sleep(remaining)
        return invalid_collision, target_samples

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
        }

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
        offscreen_width: int,
        offscreen_height: int,
    ) -> mujoco.MjModel:
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
                "type": "box",
                "size": " ".join(f"{value:.8f}" for value in half),
                "density": "220",
                "friction": "1.35 0.08 0.002",
                "solref": "0.008 1",
                "solimp": "0.95 0.99 0.001",
                "group": "0",
                "rgba": "0.08 0.70 0.86 1",
            },
        )
        ET.SubElement(
            target,
            "geom",
            {
                "name": "bottle_target_visual",
                "type": "box",
                "size": " ".join(f"{value:.8f}" for value in half * 1.012),
                "mass": "0.00000001",
                "contype": "0",
                "conaffinity": "0",
                "group": "1",
                "rgba": "0.05 0.82 1.0 0.96",
                "material": "",
            },
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
        return mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))

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
