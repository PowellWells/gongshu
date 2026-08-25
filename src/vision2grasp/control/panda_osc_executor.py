"""Bounded deterministic Panda grasp execution with robosuite OSC_POSE."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import (
    ExecutionPhase,
    ExecutionResult,
    GraspCandidate,
    PandaProprioception,
)

from .interfaces import PandaControlBackend


@dataclass(frozen=True, slots=True)
class PandaOSCExecutorConfig:
    """Safety and convergence limits for the fixed Lift / Panda MVP."""

    minimum_gripper_width_m: float = 0.01
    maximum_gripper_width_m: float = 0.08
    workspace_min_m: tuple[float, float, float] = (-0.45, -0.45, 0.82)
    workspace_max_m: tuple[float, float, float] = (0.45, 0.45, 1.20)
    minimum_downward_alignment: float = 0.90
    pregrasp_offset_m: float = 0.10
    lift_offset_m: float = 0.12
    position_tolerance_m: float = 0.008
    orientation_tolerance_rad: float = 0.08
    maximum_translation_step_m: float = 0.02
    maximum_rotation_step_rad: float = 0.15
    osc_translation_scale_m: float = 0.05
    osc_rotation_scale_rad: float = 0.50
    home_open_steps: int = 6
    pregrasp_max_steps: int = 80
    descend_max_steps: int = 80
    close_steps: int = 12
    lift_max_steps: int = 80
    return_home_max_steps: int = 100
    gripper_open_action: float = -1.0
    gripper_close_action: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_gripper_width_m < self.maximum_gripper_width_m:
            raise ValueError("gripper width limits must be positive and ordered")
        workspace_min = np.asarray(self.workspace_min_m, dtype=np.float64)
        workspace_max = np.asarray(self.workspace_max_m, dtype=np.float64)
        if workspace_min.shape != (3,) or workspace_max.shape != (3,):
            raise ValueError("workspace bounds must each contain three values")
        if not np.all(np.isfinite(workspace_min)) or not np.all(
            np.isfinite(workspace_max)
        ):
            raise ValueError("workspace bounds must be finite")
        if np.any(workspace_min >= workspace_max):
            raise ValueError("workspace bounds must be strictly ordered")
        if not 0.0 <= self.minimum_downward_alignment <= 1.0:
            raise ValueError("minimum_downward_alignment must be between 0 and 1")

        positive_values = {
            "pregrasp_offset_m": self.pregrasp_offset_m,
            "lift_offset_m": self.lift_offset_m,
            "position_tolerance_m": self.position_tolerance_m,
            "orientation_tolerance_rad": self.orientation_tolerance_rad,
            "maximum_translation_step_m": self.maximum_translation_step_m,
            "maximum_rotation_step_rad": self.maximum_rotation_step_rad,
            "osc_translation_scale_m": self.osc_translation_scale_m,
            "osc_rotation_scale_rad": self.osc_rotation_scale_rad,
        }
        for name, value in positive_values.items():
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        if self.maximum_translation_step_m > self.osc_translation_scale_m:
            raise ValueError("maximum_translation_step_m exceeds OSC output scale")
        if self.maximum_rotation_step_rad > self.osc_rotation_scale_rad:
            raise ValueError("maximum_rotation_step_rad exceeds OSC output scale")

        step_limits = {
            "home_open_steps": self.home_open_steps,
            "pregrasp_max_steps": self.pregrasp_max_steps,
            "descend_max_steps": self.descend_max_steps,
            "close_steps": self.close_steps,
            "lift_max_steps": self.lift_max_steps,
            "return_home_max_steps": self.return_home_max_steps,
        }
        for name, value in step_limits.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        for name, value in (
            ("gripper_open_action", self.gripper_open_action),
            ("gripper_close_action", self.gripper_close_action),
        ):
            if not np.isfinite(value) or not -1.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between -1 and 1")


class PandaOSCGraspExecutor:
    """Execute one bounded top grasp using robot proprioception only.

    The planner and Panda ``eef_quat_site`` frames intentionally share axes:
    +X is finger closing, +Y is the orthogonal planar / object-long axis, and
    +Z runs along the fingers in the downward approach direction. The
    conversion remains explicit below so a body quaternion or differently
    mounted gripper cannot be substituted silently.
    """

    _GRASP_FROM_EEF = np.eye(4, dtype=np.float64)
    _EXPECTED_ACTION_DIMENSION = 7

    def __init__(
        self,
        backend: PandaControlBackend,
        config: PandaOSCExecutorConfig | None = None,
    ) -> None:
        self._backend = backend
        self._config = config or PandaOSCExecutorConfig()

    def execute(self, candidate: GraspCandidate) -> ExecutionResult:
        """Run HOME through RETURN_HOME; success means motion completion only."""

        visited = [ExecutionPhase.HOME]
        try:
            self._validate_backend()
            world_from_eef_grasp = self._world_from_eef_target(candidate)
            approach_world = world_from_eef_grasp[:3, 2]

            world_from_eef_pregrasp = world_from_eef_grasp.copy()
            world_from_eef_pregrasp[:3, 3] -= (
                approach_world * self._config.pregrasp_offset_m
            )
            world_from_eef_lift = world_from_eef_grasp.copy()
            world_from_eef_lift[:3, 3] -= (
                approach_world * self._config.lift_offset_m
            )
            self._validate_candidate_and_targets(
                candidate,
                world_from_eef_grasp,
                world_from_eef_pregrasp,
                world_from_eef_lift,
            )

            home = self._backend.robot_state()
            home_pose = home.world_from_eef.copy()
            for _ in range(self._config.home_open_steps):
                self._command_pose_step(home_pose, self._config.gripper_open_action)

            phases = (
                (
                    ExecutionPhase.PREGRASP,
                    world_from_eef_pregrasp,
                    self._config.pregrasp_max_steps,
                    self._config.gripper_open_action,
                ),
                (
                    ExecutionPhase.DESCEND,
                    world_from_eef_grasp,
                    self._config.descend_max_steps,
                    self._config.gripper_open_action,
                ),
            )
            for phase, target, max_steps, gripper_action in phases:
                visited.append(phase)
                if not self._move_to_pose(
                    target,
                    max_steps=max_steps,
                    gripper_action=gripper_action,
                ):
                    return self._failure(
                        candidate,
                        visited,
                        f"{phase.value} exceeded its {max_steps}-step convergence limit",
                    )

            visited.append(ExecutionPhase.CLOSE)
            for _ in range(self._config.close_steps):
                self._command_pose_step(
                    world_from_eef_grasp,
                    self._config.gripper_close_action,
                )

            remaining_phases = (
                (
                    ExecutionPhase.LIFT,
                    world_from_eef_lift,
                    self._config.lift_max_steps,
                ),
                (
                    ExecutionPhase.RETURN_HOME,
                    home_pose,
                    self._config.return_home_max_steps,
                ),
            )
            for phase, target, max_steps in remaining_phases:
                visited.append(phase)
                if not self._move_to_pose(
                    target,
                    max_steps=max_steps,
                    gripper_action=self._config.gripper_close_action,
                ):
                    return self._failure(
                        candidate,
                        visited,
                        f"{phase.value} exceeded its {max_steps}-step convergence limit",
                    )
        except (KeyError, RuntimeError, ValueError) as error:
            return self._failure(candidate, visited, str(error))

        visited.append(ExecutionPhase.SUCCEEDED)
        return ExecutionResult(
            candidate_id=candidate.candidate_id,
            success=True,
            final_phase=ExecutionPhase.SUCCEEDED,
            message="motion sequence completed; grasp outcome was not evaluated",
            visited_phases=tuple(visited),
        )

    def _validate_backend(self) -> None:
        dimension = self._backend.action_dimension
        if dimension != self._EXPECTED_ACTION_DIMENSION:
            raise ValueError(
                "Panda OSC_POSE backend must expose 7 actions "
                f"(6 arm + 1 gripper), got {dimension}"
            )

    def _world_from_eef_target(
        self, candidate: GraspCandidate
    ) -> NDArray[np.float64]:
        return np.asarray(candidate.world_from_grasp, dtype=np.float64) @ self._GRASP_FROM_EEF

    def _validate_candidate_and_targets(
        self,
        candidate: GraspCandidate,
        world_from_eef_grasp: NDArray[np.float64],
        world_from_eef_pregrasp: NDArray[np.float64],
        world_from_eef_lift: NDArray[np.float64],
    ) -> None:
        if not candidate.reachable:
            raise ValueError("candidate is marked unreachable")
        if not (
            self._config.minimum_gripper_width_m
            <= candidate.gripper_width_m
            <= self._config.maximum_gripper_width_m
        ):
            raise ValueError("candidate gripper width is outside Panda limits")
        _validate_rigid_transform(world_from_eef_grasp, "world_from_grasp")

        downward_alignment = float(
            np.dot(world_from_eef_grasp[:3, 2], np.array([0.0, 0.0, -1.0]))
        )
        if downward_alignment < self._config.minimum_downward_alignment:
            raise ValueError("candidate approach axis is not sufficiently downward")

        workspace_min = np.asarray(self._config.workspace_min_m, dtype=np.float64)
        workspace_max = np.asarray(self._config.workspace_max_m, dtype=np.float64)
        for name, pose in (
            ("grasp", world_from_eef_grasp),
            ("pregrasp", world_from_eef_pregrasp),
            ("lift", world_from_eef_lift),
        ):
            position = pose[:3, 3]
            if np.any(position < workspace_min) or np.any(position > workspace_max):
                raise ValueError(f"{name} target is outside the fixed MVP workspace")

    def _move_to_pose(
        self,
        target: NDArray[np.float64],
        *,
        max_steps: int,
        gripper_action: float,
    ) -> bool:
        for _ in range(max_steps):
            state = self._backend.robot_state()
            if self._pose_reached(state, target):
                return True
            self._apply_pose_action(state, target, gripper_action)
        return self._pose_reached(self._backend.robot_state(), target)

    def _command_pose_step(
        self, target: NDArray[np.float64], gripper_action: float
    ) -> None:
        self._apply_pose_action(self._backend.robot_state(), target, gripper_action)

    def _apply_pose_action(
        self,
        state: PandaProprioception,
        target: NDArray[np.float64],
        gripper_action: float,
    ) -> None:
        translation = target[:3, 3] - state.world_from_eef[:3, 3]
        translation = _clip_vector_norm(
            translation, self._config.maximum_translation_step_m
        )
        rotation = _rotation_vector_between(
            target[:3, :3], state.world_from_eef[:3, :3]
        )
        rotation = _clip_vector_norm(
            rotation, self._config.maximum_rotation_step_rad
        )

        action = np.zeros(self._EXPECTED_ACTION_DIMENSION, dtype=np.float64)
        action[:3] = translation / self._config.osc_translation_scale_m
        action[3:6] = rotation / self._config.osc_rotation_scale_rad
        action[6] = gripper_action
        if np.any(np.abs(action) > 1.0 + 1e-12):
            raise RuntimeError("bounded OSC action unexpectedly exceeded [-1, 1]")
        self._backend.apply_action(action)

    def _pose_reached(
        self, state: PandaProprioception, target: NDArray[np.float64]
    ) -> bool:
        position_error = float(
            np.linalg.norm(target[:3, 3] - state.world_from_eef[:3, 3])
        )
        orientation_error = float(
            np.linalg.norm(
                _rotation_vector_between(
                    target[:3, :3], state.world_from_eef[:3, :3]
                )
            )
        )
        return (
            position_error <= self._config.position_tolerance_m
            and orientation_error <= self._config.orientation_tolerance_rad
        )

    @staticmethod
    def _failure(
        candidate: GraspCandidate,
        visited: list[ExecutionPhase],
        message: str,
    ) -> ExecutionResult:
        if not visited or visited[-1] is not ExecutionPhase.FAILED:
            visited.append(ExecutionPhase.FAILED)
        return ExecutionResult(
            candidate_id=candidate.candidate_id,
            success=False,
            final_phase=ExecutionPhase.FAILED,
            message=message,
            visited_phases=tuple(visited),
        )


def _validate_rigid_transform(transform: NDArray[np.float64], name: str) -> None:
    if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
        raise ValueError(f"{name} must be a finite 4x4 matrix")
    if not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8):
        raise ValueError(f"{name} must have a rigid homogeneous bottom row")
    rotation = transform[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6):
        raise ValueError(f"{name} rotation must be orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6):
        raise ValueError(f"{name} rotation must have determinant +1")


def _clip_vector_norm(vector: NDArray[np.float64], maximum: float) -> NDArray[np.float64]:
    norm = float(np.linalg.norm(vector))
    if norm <= maximum or norm <= 1e-12:
        return vector.copy()
    return vector * (maximum / norm)


def _rotation_vector_between(
    target: NDArray[np.float64], current: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Return the base-frame rotation vector that left-multiplies current."""

    delta = target @ current.T
    cosine = float(np.clip((np.trace(delta) - 1.0) * 0.5, -1.0, 1.0))
    angle = float(np.arccos(cosine))
    skew = np.array(
        [
            delta[2, 1] - delta[1, 2],
            delta[0, 2] - delta[2, 0],
            delta[1, 0] - delta[0, 1],
        ],
        dtype=np.float64,
    )
    if angle < 1e-8:
        return 0.5 * skew
    if np.pi - angle < 1e-5:
        _, eigenvectors = np.linalg.eigh((delta + np.eye(3)) * 0.5)
        axis = eigenvectors[:, -1]
        if float(np.dot(axis, skew)) < 0.0:
            axis = -axis
        return axis * angle
    return skew * (angle / (2.0 * np.sin(angle)))
