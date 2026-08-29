"""Replaceable spatial-perception module boundaries."""

from __future__ import annotations

from typing import Protocol

from vision2grasp.contracts import RGBFrame
from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import DepthFrame, IntrinsicsObservation, SpatialObservation


class DepthProvider(Protocol):
    def infer(self, frame: RGBFrame) -> DepthFrame: ...


class CameraIntrinsicsProvider(Protocol):
    def resolve(self, frame: RGBFrame) -> IntrinsicsObservation: ...


class SpatialPerceptionProvider(Protocol):
    def analyze(self, snapshot: TargetSceneSnapshot) -> SpatialObservation: ...


class RGBDDepthProvider(DepthProvider, Protocol):
    """Reserved same-signature boundary for synchronized native RGB-D sources."""

    def infer(self, frame: RGBFrame) -> DepthFrame: ...
