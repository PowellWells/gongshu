"""Simulation truth types restricted to debugging and evaluation."""

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class GroundTruthObjectPose:
    object_name: str
    world_from_object: NDArray[np.float64]

    def __post_init__(self) -> None:
        if self.world_from_object.shape != (4, 4):
            raise ValueError("world_from_object must have shape (4, 4)")


class GroundTruthProvider(Protocol):
    def object_pose(self, object_name: str) -> GroundTruthObjectPose: ...
