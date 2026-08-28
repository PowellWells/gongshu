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
        if not self.object_name.strip():
            raise ValueError("object_name must not be empty")
        if self.world_from_object.shape != (4, 4):
            raise ValueError("world_from_object must have shape (4, 4)")
        if not np.all(np.isfinite(self.world_from_object)):
            raise ValueError("world_from_object must contain only finite values")
        if not np.allclose(
            self.world_from_object[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8
        ):
            raise ValueError("world_from_object must have a homogeneous bottom row")
        rotation = self.world_from_object[:3, :3]
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6):
            raise ValueError("world_from_object rotation must be orthonormal")
        if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6):
            raise ValueError("world_from_object rotation must have determinant +1")


class GroundTruthProvider(Protocol):
    def object_pose(self, object_name: str) -> GroundTruthObjectPose: ...
