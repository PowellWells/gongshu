"""Gongshu-owned lifecycle bridge to the optional Xiezhi runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class GongshuRuntimeContext:
    robot: str = ""
    simulation: str = ""
    scene: str = ""
    task: str = ""
    status: str = ""
    source: str = "gongshu"

    def __post_init__(self) -> None:
        for name in ("source", "robot", "simulation", "scene", "task", "status"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string")
        if self.source != "gongshu":
            raise ValueError("source must be 'gongshu'")

    def as_dict(self, *, result: str | None = None) -> dict[str, str]:
        context = {
            "source": self.source,
            "robot": self.robot,
            "simulation": self.simulation,
            "scene": self.scene,
            "task": self.task,
            "status": self.status,
        }
        if result is not None:
            context["result"] = result
        return context


@dataclass(frozen=True, slots=True)
class XiezhiLifecycleStatus:
    module: str
    status: str
    connected: bool
    last_event: str | None = None
    last_timestamp: float | None = None
    event_count: int = 0
    context: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "status": self.status,
            "connected": self.connected,
            "last_event": self.last_event,
            "last_timestamp": self.last_timestamp,
            "event_count": self.event_count,
            "context": None if self.context is None else dict(self.context),
        }


class LifecycleRuntimePort(Protocol):
    def receive_event(
        self,
        event: str,
        context: Mapping[str, Any],
        *,
        timestamp: float | None = None,
    ) -> Any: ...

    def status(self) -> Any: ...


class GongshuXiezhiLifecycleAdapter:
    """Transmit state only; never request a decision or execute an action."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        runtime: LifecycleRuntimePort | None = None,
    ) -> None:
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        self.enabled = enabled
        self._runtime = runtime

    @classmethod
    def connect(cls, *, enabled: bool = True) -> "GongshuXiezhiLifecycleAdapter":
        if not enabled:
            return cls(enabled=False)
        try:
            from xiezhi.runtime.lifecycle import XiezhiLifecycleRuntime
        except Exception:
            return cls(enabled=True)
        return cls(enabled=True, runtime=XiezhiLifecycleRuntime())

    def publish(
        self,
        event: str,
        context: GongshuRuntimeContext,
        *,
        result: str | None = None,
        timestamp: float | None = None,
    ) -> XiezhiLifecycleStatus:
        if not isinstance(context, GongshuRuntimeContext):
            raise TypeError("context must be GongshuRuntimeContext")
        if not self.enabled or self._runtime is None:
            return self.status()
        try:
            status = self._runtime.receive_event(
                event,
                context.as_dict(result=result),
                timestamp=timestamp,
            )
        except Exception:
            self._runtime = None
            return self.status()
        return self._translate_status(status)

    def status(self) -> XiezhiLifecycleStatus:
        if not self.enabled:
            return XiezhiLifecycleStatus("xiezhi", "disabled", False)
        if self._runtime is None:
            return XiezhiLifecycleStatus("xiezhi", "unavailable", False)
        try:
            return self._translate_status(self._runtime.status())
        except Exception:
            self._runtime = None
            return XiezhiLifecycleStatus("xiezhi", "unavailable", False)

    @staticmethod
    def _translate_status(value: Any) -> XiezhiLifecycleStatus:
        data = value.as_dict()
        return XiezhiLifecycleStatus(
            module=str(data["module"]),
            status=str(data["status"]),
            connected=bool(data["connected"]),
            last_event=data.get("last_event"),
            last_timestamp=data.get("last_timestamp"),
            event_count=int(data.get("event_count", 0)),
            context=data.get("context"),
        )
