"""Target-perception module boundaries."""

from __future__ import annotations

from typing import Protocol, Sequence

from vision2grasp.contracts import RGBFrame

from .contracts import TargetInstance


class TargetInstanceSegmenter(Protocol):
    """Generate model-neutral target regions from one immutable RGB frame."""

    def predict(self, frame: RGBFrame) -> Sequence[TargetInstance]: ...
