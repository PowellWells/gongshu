"""Replaceable spatial-perception module boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from vision2grasp.contracts import RGBFrame
from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import (
    DepthFrame,
    IntrinsicsObservation,
    IntrinsicsSource,
    SpatialObservation,
    SpatialStage,
)


SpatialProgressCallback = Callable[[SpatialStage, Mapping[str, object] | None], None]


class DepthProvider(Protocol):
    def infer(
        self,
        frame: RGBFrame,
        progress: SpatialProgressCallback | None = None,
    ) -> DepthFrame: ...


class CameraIntrinsicsProvider(Protocol):
    def resolve(self, frame: RGBFrame) -> IntrinsicsObservation: ...


class CameraIntrinsicsCandidateProvider(Protocol):
    """Optional source used by the ordered device-agnostic resolver."""

    source: IntrinsicsSource

    def resolve_candidate(self, frame: RGBFrame) -> IntrinsicsObservation | None: ...


class SpatialPerceptionProvider(Protocol):
    def analyze(
        self,
        snapshot: TargetSceneSnapshot,
        progress: SpatialProgressCallback | None = None,
    ) -> SpatialObservation: ...


class RGBDDepthProvider(DepthProvider, Protocol):
    """Reserved same-signature boundary for synchronized native RGB-D sources."""

    def infer(
        self,
        frame: RGBFrame,
        progress: SpatialProgressCallback | None = None,
    ) -> DepthFrame: ...
