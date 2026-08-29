"""Contracts separating GraspPlan from MuJoCo validation internals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vision2grasp.grasp_planning import GraspPlan


VALIDATION_REQUEST_SCHEMA_VERSION = "gongshu.validation-request/v1"


class CameraMode(str, Enum):
    CINEMATIC = "CINEMATIC"
    AUTO_FOLLOW = "AUTO_FOLLOW"
    MANUAL = "MANUAL"


class SimulationState(str, Enum):
    WAITING = "WAITING"
    INITIALIZING = "INITIALIZING"
    HOME = "HOME"
    PRE_GRASP = "PRE_GRASP"
    APPROACH = "APPROACH"
    ALIGN = "ALIGN"
    CLOSE = "CLOSE"
    LIFT = "LIFT"
    VERIFY = "VERIFY"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ValidationSceneTransform:
    """Map relative plan geometry into a safe simulation-only workspace."""

    name: str
    target_position_world: NDArray[np.float64]
    target_yaw_rad: float
    target_extents_world: NDArray[np.float64]
    grasp_position_world: NDArray[np.float64]
    approach_world: NDArray[np.float64]
    closing_world: NDArray[np.float64]
    calibration_state: str = "UNCALIBRATED"
    execution_scope: str = "SIMULATION_ONLY"

    def __post_init__(self) -> None:
        if self.name != "NORMALIZED_VALIDATION_SCENE":
            raise ValueError("unsupported validation scene transform")
        if self.calibration_state != "UNCALIBRATED":
            raise ValueError("v0.6 validation transform must remain UNCALIBRATED")
        if self.execution_scope != "SIMULATION_ONLY":
            raise ValueError("validation transform must remain SIMULATION_ONLY")
        for name in (
            "target_position_world",
            "target_extents_world",
            "grasp_position_world",
            "approach_world",
            "closing_world",
        ):
            value = np.asarray(getattr(self, name), dtype=np.float64)
            if value.shape != (3,) or not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must be a finite 3-vector")
            if name == "target_extents_world" and np.any(value <= 0.0):
                raise ValueError("target extents must be positive")
            if name in {"approach_world", "closing_world"} and not np.isclose(
                np.linalg.norm(value), 1.0, atol=1e-6
            ):
                raise ValueError(f"{name} must be a unit vector")
            immutable = np.ascontiguousarray(value.copy())
            immutable.setflags(write=False)
            object.__setattr__(self, name, immutable)

    @classmethod
    def from_grasp_plan(
        cls,
        plan: GraspPlan,
        *,
        table_top_z: float = 0.80,
        target_xy: tuple[float, float] = (0.0, 0.0),
    ) -> "ValidationSceneTransform":
        # Plan extents are [closing, major, optical-depth]. Their relative
        # sizes are preserved while Camera XYZ is deliberately not treated as
        # a calibrated robot pose.
        extents = np.asarray(plan.object_extents_xyz, dtype=np.float64)
        target_position = np.array(
            [target_xy[0], target_xy[1], table_top_z + extents[2] / 2.0],
            dtype=np.float64,
        )
        closing = np.array(
            [np.cos(plan.grasp_angle), np.sin(plan.grasp_angle), 0.0], dtype=np.float64
        )
        return cls(
            name="NORMALIZED_VALIDATION_SCENE",
            target_position_world=target_position,
            target_yaw_rad=plan.grasp_angle,
            target_extents_world=extents,
            grasp_position_world=target_position.copy(),
            approach_world=np.array([0.0, 0.0, -1.0], dtype=np.float64),
            closing_world=closing,
        )

    def public_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "target_position_world": self.target_position_world.tolist(),
            "target_yaw_rad": self.target_yaw_rad,
            "target_extents_world": self.target_extents_world.tolist(),
            "grasp_position_world": self.grasp_position_world.tolist(),
            "approach_world": self.approach_world.tolist(),
            "closing_world": self.closing_world.tolist(),
            "calibration_state": self.calibration_state,
            "execution_scope": self.execution_scope,
        }


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    grasp_plan: GraspPlan
    scene_transform: ValidationSceneTransform

    def __post_init__(self) -> None:
        if self.scene_transform.name != "NORMALIZED_VALIDATION_SCENE":
            raise ValueError("ValidationRequest requires normalized validation scene")

    @classmethod
    def from_grasp_plan(cls, plan: GraspPlan) -> "ValidationRequest":
        return cls(plan, ValidationSceneTransform.from_grasp_plan(plan))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": VALIDATION_REQUEST_SCHEMA_VERSION,
            "grasp_plan": self.grasp_plan.public_metadata(),
            "scene_transform": self.scene_transform.public_metadata(),
        }


@dataclass(frozen=True, slots=True)
class ValidationResult:
    state: SimulationState
    reason: str | None
    state_machine_complete: bool
    invalid_table_collision: bool
    gripper_close_executed: bool
    lift_height_m: float
    stable_window_passed: bool

    @property
    def succeeded(self) -> bool:
        return self.state is SimulationState.SUCCESS

    def public_metadata(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "reason": self.reason,
            "state_machine_complete": self.state_machine_complete,
            "invalid_table_collision": self.invalid_table_collision,
            "gripper_close_executed": self.gripper_close_executed,
            "lift_height_m": self.lift_height_m,
            "stable_window_passed": self.stable_window_passed,
            "validation_result": (
                "Simulation Validation SUCCESS"
                if self.succeeded
                else "Simulation Validation FAILED"
            ),
        }

