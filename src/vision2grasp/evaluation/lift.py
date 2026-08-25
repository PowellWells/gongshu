"""Execution-after evaluation isolated from the truth-free main pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from .ground_truth import GroundTruthObjectPose


class _BottleTruthSource(Protocol):
    def _evaluation_object_pose(
        self, object_name: str
    ) -> NDArray[np.float64]: ...


@dataclass(frozen=True, slots=True)
class BottleLiftEvaluationConfig:
    object_name: str = "bottle"
    minimum_vertical_displacement_m: float = 0.03

    def __post_init__(self) -> None:
        if not self.object_name.strip():
            raise ValueError("object_name must not be empty")
        if (
            not np.isfinite(self.minimum_vertical_displacement_m)
            or self.minimum_vertical_displacement_m <= 0.0
        ):
            raise ValueError("minimum_vertical_displacement_m must be positive")


@dataclass(frozen=True, slots=True)
class BottleLiftEvaluation:
    object_name: str
    success: bool
    motion_completed: bool
    initial_height_m: float
    final_height_m: float
    vertical_displacement_m: float
    total_displacement_m: float
    minimum_vertical_displacement_m: float


class RobosuiteBottleLiftEvaluator:
    """Read BottleLift truth before and after, never during the main run."""

    def __init__(
        self,
        source: _BottleTruthSource,
        config: BottleLiftEvaluationConfig | None = None,
    ) -> None:
        self._source = source
        self._config = config or BottleLiftEvaluationConfig()
        self._initial_pose: GroundTruthObjectPose | None = None

    def begin_episode(self) -> None:
        self._initial_pose = self._read_pose()

    def finish_episode(self, *, motion_completed: bool) -> BottleLiftEvaluation:
        if self._initial_pose is None:
            raise RuntimeError("begin_episode() must be called before finish_episode()")
        initial = self._initial_pose
        final = self._read_pose()
        self._initial_pose = None

        initial_position = initial.world_from_object[:3, 3]
        final_position = final.world_from_object[:3, 3]
        vertical_displacement = float(final_position[2] - initial_position[2])
        total_displacement = float(np.linalg.norm(final_position - initial_position))
        success = bool(
            motion_completed
            and vertical_displacement
            >= self._config.minimum_vertical_displacement_m
        )
        return BottleLiftEvaluation(
            object_name=self._config.object_name,
            success=success,
            motion_completed=motion_completed,
            initial_height_m=float(initial_position[2]),
            final_height_m=float(final_position[2]),
            vertical_displacement_m=vertical_displacement,
            total_displacement_m=total_displacement,
            minimum_vertical_displacement_m=(
                self._config.minimum_vertical_displacement_m
            ),
        )

    def _read_pose(self) -> GroundTruthObjectPose:
        matrix = np.asarray(
            self._source._evaluation_object_pose(self._config.object_name),
            dtype=np.float64,
        )
        return GroundTruthObjectPose(
            object_name=self._config.object_name,
            world_from_object=matrix.copy(),
        )
