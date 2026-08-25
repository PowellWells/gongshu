"""Interfaces implemented by MuJoCo / robosuite adapters."""

from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import RGBDFrame


class RGBDSimulator(Protocol):
    def reset(self, *, seed: int | None = None) -> RGBDFrame: ...

    def capture(self) -> RGBDFrame: ...

    def apply_action(self, action: NDArray[np.float64]) -> RGBDFrame: ...

    def close(self) -> None: ...
