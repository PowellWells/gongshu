"""Asynchronous MuJoCo validation state and MJPEG frame service."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Final

from vision2grasp.grasp_planning import GraspPlan

from .validation_contracts import CameraMode, SimulationState, ValidationRequest, ValidationResult


VALIDATION_SCHEMA_VERSION: Final = "gongshu.mujoco-validation/v1"


class MuJoCoValidationService:
    def __init__(
        self,
        backend_factory: Callable[[ValidationRequest, Any], Any] | None = None,
    ) -> None:
        self._backend_factory = backend_factory
        self._lock = threading.RLock()
        self._frame_condition = threading.Condition(self._lock)
        self._state = SimulationState.WAITING
        self._message = "等待仿真验证 WAITING"
        self._reason: str | None = None
        self._revision = 0
        self._frame_revision = 0
        self._frame_jpeg: bytes | None = None
        self._telemetry: dict[str, object] = {}
        self._request: ValidationRequest | None = None
        self._result: ValidationResult | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._camera_director: Any | None = None
        self._camera_mode = CameraMode.CINEMATIC

    def start(self, plan: GraspPlan) -> dict[str, object]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("MuJoCo validation is already running")
            self._request = ValidationRequest.from_grasp_plan(plan)
            self._result = None
            self._reason = None
            self._telemetry = {}
            self._frame_jpeg = None
            from .native_panda_validation import CameraDirector

            self._camera_director = CameraDirector(CameraMode.CINEMATIC)
            self._camera_mode = CameraMode.CINEMATIC
            self._set_state_locked(SimulationState.INITIALIZING, "正在初始化 MuJoCo Validation")
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_worker, name="gongshu-mujoco-validation", daemon=True)
            self._thread.start()
            return self.snapshot()

    def reset(self) -> dict[str, object]:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        with self._lock:
            self._thread = None
            self._request = None
            self._result = None
            self._reason = None
            self._telemetry = {}
            self._frame_jpeg = None
            self._set_state_locked(SimulationState.WAITING, "等待仿真验证 WAITING")
            return self.snapshot()

    def set_camera_mode(self, mode: str) -> dict[str, object]:
        camera_mode = CameraMode(str(mode).upper())
        self._camera_mode = camera_mode
        if self._camera_director is not None:
            self._camera_director.set_mode(camera_mode)
        with self._lock:
            self._revision += 1
            return self.snapshot()

    def manual_camera(self, payload: dict[str, object]) -> dict[str, object]:
        if self._camera_director is None:
            raise RuntimeError("MuJoCo camera is not initialized")
        self._camera_director.manual_delta(
            rotate_x=float(payload.get("rotate_x", 0.0)),
            rotate_y=float(payload.get("rotate_y", 0.0)),
            pan_x=float(payload.get("pan_x", 0.0)),
            pan_y=float(payload.get("pan_y", 0.0)),
            zoom=float(payload.get("zoom", 0.0)),
        )
        with self._lock:
            self._revision += 1
            return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "schema_version": VALIDATION_SCHEMA_VERSION,
                "status": self._state.value,
                "message": self._message,
                "reason": self._reason,
                "revision": self._revision,
                "frame_revision": self._frame_revision,
                "camera_mode": (
                    self._camera_director.mode.value
                    if self._camera_director is not None
                    else self._camera_mode.value
                ),
                "request": None if self._request is None else self._request.public_metadata(),
                "telemetry": dict(self._telemetry),
                "result": None if self._result is None else self._result.public_metadata(),
                "media": {"stream_available": self._frame_jpeg is not None},
            }

    def wait_for_frame(self, revision: int, *, timeout: float = 2.0) -> tuple[int, bytes] | None:
        deadline = time.monotonic() + timeout
        with self._frame_condition:
            while self._frame_revision <= revision or self._frame_jpeg is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return None
                self._frame_condition.wait(remaining)
            return self._frame_revision, bytes(self._frame_jpeg)

    def latest_frame(self) -> bytes | None:
        with self._lock:
            return None if self._frame_jpeg is None else bytes(self._frame_jpeg)

    def _run_worker(self) -> None:
        try:
            assert self._request is not None
            assert self._camera_director is not None
            if self._backend_factory is None:
                from .native_panda_validation import NativePandaValidation

                backend = NativePandaValidation(self._request, self._camera_director)
            else:
                backend = self._backend_factory(self._request, self._camera_director)
            result = backend.run(self._on_frame, self._stop_event)
            with self._lock:
                self._result = result
                self._reason = result.reason
                self._set_state_locked(
                    result.state,
                    "仿真验证成功 Simulation Validation SUCCESS"
                    if result.succeeded
                    else f"仿真验证失败 Simulation Validation FAILED · {result.reason or 'State Error'}",
                )
        except Exception as error:
            with self._lock:
                self._reason = str(error) or "State Error"
                self._set_state_locked(SimulationState.FAILED, f"仿真验证失败 Simulation Validation FAILED · {self._reason}")

    def _on_frame(self, state: SimulationState, jpeg: bytes, telemetry: dict[str, object]) -> None:
        with self._frame_condition:
            # Final showcase frames are emitted before run() returns its
            # validated result. Keep the service non-terminal until that
            # result is installed atomically, while exposing the rendered
            # robot state through telemetry for the HUD.
            if state not in {SimulationState.SUCCESS, SimulationState.FAILED} and self._state is not state:
                self._set_state_locked(state, f"MuJoCo · {state.value}")
            self._frame_jpeg = bytes(jpeg)
            self._telemetry = dict(telemetry)
            self._frame_revision += 1
            self._frame_condition.notify_all()

    def _set_state_locked(self, state: SimulationState, message: str) -> None:
        self._state = state
        self._message = message
        self._revision += 1
