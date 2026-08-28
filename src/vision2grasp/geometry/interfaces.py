"""Interfaces for mask-based RGB-D localization."""

from typing import Protocol

from vision2grasp.contracts import Detection2D, LocalizedTarget, RGBDFrame


class TargetLocalizer(Protocol):
    def localize(self, frame: RGBDFrame, detection: Detection2D) -> LocalizedTarget: ...
