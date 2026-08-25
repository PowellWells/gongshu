"""Interfaces for four-view demo rendering."""

from typing import Mapping, Protocol, Sequence

import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import (
    Detection2D,
    ExecutionResult,
    GraspCandidate,
    LocalizedTarget,
    RGBDFrame,
)


class RunVisualizer(Protocol):
    def render(
        self,
        *,
        frame: RGBDFrame,
        detection: Detection2D | None,
        target: LocalizedTarget | None,
        candidates: Sequence[GraspCandidate],
        execution: ExecutionResult | None,
    ) -> Mapping[str, NDArray[np.uint8]]: ...
