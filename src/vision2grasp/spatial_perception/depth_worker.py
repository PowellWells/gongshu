"""Killable persistent process that owns the lazy Depth Anything model."""

from __future__ import annotations

from dataclasses import dataclass
import multiprocessing as mp
from pathlib import Path
from queue import Empty
import threading
import time
from typing import Any
from uuid import uuid4

from vision2grasp.contracts import RGBFrame

from .contracts import DepthFrame, SpatialStage
from .interfaces import SpatialProgressCallback
from .monocular import (
    DepthUnavailableError,
    MonocularDepthConfig,
    MonocularDepthProvider,
)


class SpatialWorkerTimeoutError(DepthUnavailableError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class SpatialWatchdogConfig:
    heartbeat_interval_s: float = 0.5
    download_warning_stall_s: float = 30.0
    download_timeout_stall_s: float = 120.0
    checksum_warning_s: float = 15.0
    checksum_timeout_s: float = 60.0
    model_loading_warning_s: float = 15.0
    model_loading_timeout_s: float = 60.0
    depth_inference_warning_s: float = 15.0
    depth_inference_timeout_s: float = 60.0
    point_cloud_warning_s: float = 5.0
    point_cloud_timeout_s: float = 30.0
    spatial_computing_warning_s: float = 5.0
    spatial_computing_timeout_s: float = 30.0

    def __post_init__(self) -> None:
        pairs = (
            (self.download_warning_stall_s, self.download_timeout_stall_s),
            (self.checksum_warning_s, self.checksum_timeout_s),
            (self.model_loading_warning_s, self.model_loading_timeout_s),
            (self.depth_inference_warning_s, self.depth_inference_timeout_s),
            (self.point_cloud_warning_s, self.point_cloud_timeout_s),
            (self.spatial_computing_warning_s, self.spatial_computing_timeout_s),
        )
        if self.heartbeat_interval_s <= 0.0:
            raise ValueError("heartbeat_interval_s must be positive")
        if any(warning <= 0.0 or timeout <= warning for warning, timeout in pairs):
            raise ValueError("watchdog timeouts must be positive and exceed warnings")


def _depth_worker_main(
    commands: Any,
    events: Any,
    config: MonocularDepthConfig,
) -> None:
    provider = MonocularDepthProvider(config)
    while True:
        command = commands.get()
        if command.get("kind") == "STOP":
            return
        if command.get("kind") != "INFER":
            continue
        request_id = str(command["request_id"])
        frame = command["frame"]

        def report(stage: SpatialStage, details: object = None) -> None:
            events.put(
                {
                    "kind": "PROGRESS",
                    "request_id": request_id,
                    "stage": stage.value,
                    "details": dict(details) if isinstance(details, dict) else {},
                    "sent_at": time.time(),
                }
            )

        try:
            result = provider.infer(frame, report)
            events.put(
                {
                    "kind": "RESULT",
                    "request_id": request_id,
                    "result": result,
                    "sent_at": time.time(),
                }
            )
        except BaseException as error:
            events.put(
                {
                    "kind": "ERROR",
                    "request_id": request_id,
                    "code": getattr(error, "code", "DEPTH_UNAVAILABLE"),
                    "message": str(error),
                    "sent_at": time.time(),
                }
            )


class PersistentDepthWorkerProvider:
    """DepthProvider proxy with one reusable, killable model-owning process."""

    def __init__(
        self,
        config: MonocularDepthConfig | None = None,
        watchdog: SpatialWatchdogConfig | None = None,
        *,
        multiprocessing_context: str = "spawn",
        worker_target: Any = _depth_worker_main,
    ) -> None:
        self._config = config or MonocularDepthConfig()
        self._watchdog = watchdog or SpatialWatchdogConfig()
        self._context = mp.get_context(multiprocessing_context)
        self._worker_target = worker_target
        self._lifecycle_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._process: Any | None = None
        self._commands: Any | None = None
        self._events: Any | None = None
        self._model_ready = False
        self._active_request_id: str | None = None
        self._generation = 0

    @property
    def model_ready(self) -> bool:
        return self._model_ready and self._process is not None and self._process.is_alive()

    @property
    def worker_pid(self) -> int | None:
        process = self._process
        return None if process is None else process.pid

    def infer(
        self,
        frame: RGBFrame,
        progress: SpatialProgressCallback | None = None,
    ) -> DepthFrame:
        with self._request_lock:
            self._ensure_worker()
            assert self._commands is not None
            assert self._events is not None
            commands = self._commands
            events = self._events
            generation = self._generation
            request_id = uuid4().hex
            self._active_request_id = request_id
            cold_start = not self.model_ready
            commands.put(
                {"kind": "INFER", "request_id": request_id, "frame": frame}
            )
            current_stage = SpatialStage.QUEUED
            stage_started = time.monotonic()
            last_download_progress = stage_started
            last_download_bytes = 0
            warned = False
            self._report(
                progress,
                current_stage,
                {
                    "cold_start": cold_start,
                    "worker_pid": self.worker_pid,
                    "worker_model_ready": self.model_ready,
                },
            )
            try:
                while True:
                    if generation != self._generation:
                        error = DepthUnavailableError(
                            "persistent depth request was cancelled by worker restart"
                        )
                        error.code = "SPATIAL_JOB_CANCELLED"
                        raise error
                    process = self._process
                    if process is None or not process.is_alive():
                        self._model_ready = False
                        raise DepthUnavailableError(
                            "persistent depth worker exited before returning a result"
                        )
                    try:
                        event = events.get(
                            timeout=self._watchdog.heartbeat_interval_s
                        )
                    except (Empty, OSError, ValueError):
                        if generation != self._generation:
                            error = DepthUnavailableError(
                                "persistent depth request was cancelled by worker restart"
                            )
                            error.code = "SPATIAL_JOB_CANCELLED"
                            raise error
                        event = None
                    now = time.monotonic()
                    if event is not None and event.get("request_id") == request_id:
                        kind = event.get("kind")
                        if kind == "PROGRESS":
                            stage = SpatialStage(str(event["stage"]))
                            details = dict(event.get("details") or {})
                            if stage is not current_stage:
                                current_stage = stage
                                stage_started = now
                                warned = False
                                if stage is SpatialStage.MODEL_DOWNLOADING:
                                    last_download_progress = now
                                    last_download_bytes = 0
                            if stage is SpatialStage.MODEL_DOWNLOADING:
                                downloaded = int(details.get("bytes_downloaded") or 0)
                                if downloaded > last_download_bytes:
                                    last_download_bytes = downloaded
                                    last_download_progress = now
                            details.update(
                                {
                                    "cold_start": cold_start,
                                    "worker_pid": self.worker_pid,
                                    "heartbeat": True,
                                }
                            )
                            self._report(progress, stage, details)
                        elif kind == "RESULT":
                            result = event["result"]
                            if not isinstance(result, DepthFrame):
                                raise DepthUnavailableError(
                                    "persistent depth worker returned an invalid result"
                                )
                            self._model_ready = True
                            return result
                        elif kind == "ERROR":
                            error = DepthUnavailableError(str(event.get("message") or ""))
                            error.code = str(event.get("code") or "DEPTH_UNAVAILABLE")
                            raise error

                    warning_s, timeout_s, timeout_code, elapsed = self._limits(
                        current_stage,
                        now=now,
                        stage_started=stage_started,
                        last_download_progress=last_download_progress,
                    )
                    if warning_s is not None and elapsed >= warning_s:
                        warned = True
                    if timeout_s is not None and elapsed >= timeout_s:
                        self._restart_worker_locked()
                        raise SpatialWorkerTimeoutError(
                            timeout_code,
                            f"{current_stage.value} exceeded {timeout_s:.1f} s",
                        )
                    self._report(
                        progress,
                        current_stage,
                        {
                            "cold_start": cold_start,
                            "worker_pid": self.worker_pid,
                            "heartbeat": True,
                            "taking_longer": warned,
                            "watchdog_elapsed_s": elapsed,
                            "watchdog_warning_s": warning_s,
                            "watchdog_timeout_s": timeout_s,
                        },
                    )
            except BaseException:
                if self._active_request_id == request_id:
                    self._active_request_id = None
                raise
            finally:
                if self._active_request_id == request_id:
                    self._active_request_id = None

    def cancel_current(self) -> None:
        with self._lifecycle_lock:
            if self._active_request_id is not None:
                self._restart_worker_locked()

    def close(self) -> None:
        with self._lifecycle_lock:
            self._stop_worker_locked()

    def _ensure_worker(self) -> None:
        with self._lifecycle_lock:
            if self._process is not None and self._process.is_alive():
                return
            self._commands = self._context.Queue()
            self._events = self._context.Queue()
            self._process = self._context.Process(
                target=self._worker_target,
                args=(self._commands, self._events, self._config),
                name="gongshu-depth-worker",
                daemon=True,
            )
            self._process.start()
            self._generation += 1
            self._model_ready = False

    def _restart_worker_locked(self) -> None:
        with self._lifecycle_lock:
            # Invalidate in-flight readers before waiting for process shutdown so
            # cancellation cannot be misreported as the old stage's timeout.
            self._generation += 1
            self._stop_worker_locked()
            self._ensure_worker()

    def _stop_worker_locked(self) -> None:
        process = self._process
        commands = self._commands
        if process is not None and process.is_alive():
            try:
                if commands is not None:
                    commands.put_nowait({"kind": "STOP"})
                process.join(timeout=1.0)
            except Exception:
                pass
            if process.is_alive():
                process.terminate()
                process.join(timeout=3.0)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=2.0)
        for queue in (self._commands, self._events):
            if queue is not None:
                try:
                    queue.cancel_join_thread()
                    queue.close()
                except Exception:
                    pass
        self._process = None
        self._commands = None
        self._events = None
        self._model_ready = False
        self._active_request_id = None

    def _limits(
        self,
        stage: SpatialStage,
        *,
        now: float,
        stage_started: float,
        last_download_progress: float,
    ) -> tuple[float | None, float | None, str, float]:
        if stage is SpatialStage.MODEL_DOWNLOADING:
            elapsed = now - last_download_progress
            return (
                self._watchdog.download_warning_stall_s,
                self._watchdog.download_timeout_stall_s,
                "DOWNLOAD_TIMEOUT",
                elapsed,
            )
        elapsed = now - stage_started
        if stage is SpatialStage.CHECKSUM_VERIFYING:
            return (
                self._watchdog.checksum_warning_s,
                self._watchdog.checksum_timeout_s,
                "CHECKSUM_TIMEOUT",
                elapsed,
            )
        if stage is SpatialStage.MODEL_LOADING:
            return (
                self._watchdog.model_loading_warning_s,
                self._watchdog.model_loading_timeout_s,
                "MODEL_LOAD_TIMEOUT",
                elapsed,
            )
        if stage is SpatialStage.DEPTH_INFERENCE:
            return (
                self._watchdog.depth_inference_warning_s,
                self._watchdog.depth_inference_timeout_s,
                "DEPTH_INFERENCE_TIMEOUT",
                elapsed,
            )
        return None, None, "DEPTH_WORKER_TIMEOUT", elapsed

    @staticmethod
    def _report(
        progress: SpatialProgressCallback | None,
        stage: SpatialStage,
        details: dict[str, object],
    ) -> None:
        if progress is not None:
            progress(stage, details)
