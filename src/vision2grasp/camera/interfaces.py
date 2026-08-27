"""Camera acquisition contracts that do not depend on perception algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from vision2grasp.contracts import RGBFrame


@dataclass(frozen=True, slots=True)
class StillCapture:
    """One explicitly captured high-resolution image and its original bytes."""

    frame: RGBFrame
    content_type: str
    original_bytes: bytes
    captured_at: str


class CameraProvider(Protocol):
    """Stable boundary consumed by future perception modules."""

    @property
    def provider_name(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def capture(self) -> RGBFrame: ...

    def snapshot(self) -> dict[str, object]: ...


__all__ = ["CameraProvider", "StillCapture"]
