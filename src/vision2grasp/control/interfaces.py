"""Interfaces for deterministic Panda grasp execution."""

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import ExecutionResult, GraspCandidate, PandaProprioception


class PandaControlBackend(Protocol):
    """Minimal OSC_POSE boundary: actions plus robot proprioception only."""

    @property
    def action_dimension(self) -> int: ...

    def robot_state(self) -> PandaProprioception: ...

    def apply_action(self, action: NDArray[np.float64]) -> object: ...


class GraspExecutor(Protocol):
    def execute(self, candidate: GraspCandidate) -> ExecutionResult: ...
