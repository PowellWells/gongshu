"""Shared visual-input boundary for simulation, cameras, and image files."""

from typing import Protocol, TypeAlias

from vision2grasp.contracts import RGBDFrame, RGBFrame


VisionFrame: TypeAlias = RGBFrame | RGBDFrame


class FrameSource(Protocol):
    @property
    def source_name(self) -> str: ...

    def capture(self) -> VisionFrame: ...

    def close(self) -> None: ...


__all__ = ["FrameSource", "VisionFrame"]
