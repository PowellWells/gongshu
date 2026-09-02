"""Asynchronous physics validation plus session-only recording playback."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable, Final
import uuid

import cv2
import numpy as np

from vision2grasp.grasp_planning import GraspPlan, GraspPlanningOutcome
from vision2grasp.target_perception import TargetSceneSnapshot

from .appearance import extract_target_appearance
from .recording import (
    PlaybackSession,
    PlanningVisualizationRecording,
    SimulationRecording,
    default_exports_root,
    list_saved_runs,
    load_planning_visualization,
    load_recording,
    save_recording,
    save_planning_visualization,
    utc_timestamp,
)
from .validation_contracts import (
    CameraMode,
    SimulationAttempt,
    SimulationState,
    ValidationRequest,
    ValidationResult,
    ValidationScenario,
)


VALIDATION_SCHEMA_VERSION: Final = "gongshu.mujoco-validation/v4"
_PLAYBACK_SPEEDS: Final = (0.25, 0.5, 1.0, 2.0)


class MuJoCoValidationService:
    """Own one physics worker and a bounded, non-persistent session history."""

    def __init__(
        self,
        backend_factory: Callable[[ValidationRequest, Any], Any] | None = None,
        *,
        failure_target_offset_m: tuple[float, float, float] = (0.14, 0.0, 0.0),
        max_session_recordings: int = 8,
        recordings_root: Path | None = None,
        exports_root: Path | None = None,
        minimum_gripper_width_m: float = 0.01,
        maximum_gripper_width_m: float = 0.08,
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
        self._camera_mode = CameraMode.AUTO_CINEMATIC
        self._failure_target_offset_m = tuple(float(value) for value in failure_target_offset_m)
        if len(self._failure_target_offset_m) != 3:
            raise ValueError("failure_target_offset_m must contain three values")
        self._started_at = 0.0
        self._state_history: list[dict[str, object]] = []
        self._max_session_recordings = max(1, int(max_session_recordings))
        self._session_recordings: list[SimulationRecording] = []
        self._current_recording: SimulationRecording | None = None
        self._planning_visualizations: list[PlanningVisualizationRecording] = []
        self._current_visualization: PlanningVisualizationRecording | None = None
        self._playback = PlaybackSession()
        self._playback_event = threading.Event()
        self._playback_shutdown = threading.Event()
        self._recordings_root = recordings_root
        self._exports_root = exports_root
        self._minimum_gripper_width_m = float(minimum_gripper_width_m)
        self._maximum_gripper_width_m = float(maximum_gripper_width_m)
        if (
            not 0.0 < self._minimum_gripper_width_m
            <= self._maximum_gripper_width_m
        ):
            raise ValueError("Panda gripper width limits are invalid")
        self._export_lock = threading.Lock()
        self._playback_thread = threading.Thread(
            target=self._playback_loop, name="gongshu-recording-playback", daemon=True
        )
        self._playback_thread.start()

    def start(
        self,
        plan: GraspPlan | SimulationAttempt,
        *,
        scenario: ValidationScenario | str = ValidationScenario.NOMINAL,
        snapshot: TargetSceneSnapshot | None = None,
    ) -> dict[str, object]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("MuJoCo validation is already running")
            appearance = None
            appearance_failure_reason = None
            if snapshot is not None:
                if snapshot.snapshot_id != plan.snapshot_id:
                    raise ValueError("Validation Scene Snapshot does not match GraspPlan")
                if snapshot.frame.frame_id != plan.source_frame_id:
                    raise ValueError("Validation source frame does not match GraspPlan")
                if snapshot.target.instance_id != plan.target_id:
                    raise ValueError("Validation target does not match GraspPlan")
                try:
                    appearance = extract_target_appearance(snapshot)
                except Exception as error:
                    appearance_failure_reason = (
                        f"{type(error).__name__}: {str(error) or 'texture generation failed'}"
                    )
            else:
                appearance_failure_reason = "NO_TARGET_SCENE_SNAPSHOT"
            self._request = ValidationRequest.from_grasp_plan(
                plan,
                scenario=scenario,
                failure_target_offset_m=self._failure_target_offset_m,
                target_appearance=appearance,
                appearance_failure_reason=appearance_failure_reason,
            )
            self._result = None
            self._reason = None
            self._telemetry = {}
            self._frame_jpeg = None
            self._current_recording = None
            self._current_visualization = None
            self._playback = PlaybackSession()
            from .native_panda_validation import CameraDirector

            self._camera_director = CameraDirector(CameraMode.AUTO_CINEMATIC)
            self._camera_mode = CameraMode.AUTO_CINEMATIC
            self._started_at = time.monotonic()
            self._state_history = []
            self._set_state_locked(SimulationState.INITIALIZING, "正在初始化 MuJoCo Validation")
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_worker, name="gongshu-mujoco-validation", daemon=True
            )
            self._thread.start()
            return self.snapshot()

    def start_rejected_attempt(
        self,
        outcome: GraspPlanningOutcome,
        *,
        snapshot: TargetSceneSnapshot,
        scenario: ValidationScenario | str = ValidationScenario.NOMINAL,
    ) -> dict[str, object]:
        """Execute the highest-ranked rejected candidate without changing planning."""

        if outcome.plan is not None:
            raise ValueError("ready planning outcomes must start from their GraspPlan")
        if not outcome.candidates:
            raise RuntimeError("Simulation Attempt is unavailable because no candidate exists")
        candidate = outcome.candidates[0]
        if candidate.target_instance_id != snapshot.target.instance_id:
            raise ValueError("Simulation candidate does not match selected target")
        if candidate.source_frame_id != snapshot.frame.frame_id:
            raise ValueError("Simulation candidate does not match selected source frame")
        attempt = SimulationAttempt.from_rejected_candidate(
            candidate,
            snapshot_id=snapshot.snapshot_id,
            object_extents_xyz=outcome.object_extents_xyz,
            candidate_count=len(outcome.candidates),
            planning_reason=outcome.rejection_reason or "NO_VALID_CANDIDATE",
            minimum_gripper_width_m=self._minimum_gripper_width_m,
            maximum_gripper_width_m=self._maximum_gripper_width_m,
        )
        return self.start(attempt, scenario=scenario, snapshot=snapshot)

    def reset(self) -> dict[str, object]:
        """Close the active run but intentionally retain bounded Session History."""

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
            self._current_recording = None
            self._current_visualization = None
            self._started_at = 0.0
            self._state_history = []
            self._playback = PlaybackSession()
            self._set_state_locked(SimulationState.WAITING, "等待仿真验证 WAITING")
            self._playback_event.set()
            return self.snapshot()

    def close(self) -> None:
        self.reset()
        self._playback_shutdown.set()
        self._playback_event.set()
        self._playback_thread.join(timeout=3.0)

    def set_camera_mode(self, mode: str) -> dict[str, object]:
        camera_mode = CameraMode.parse(mode)
        with self._lock:
            self._camera_mode = camera_mode
            self._playback.camera_mode = camera_mode
            if camera_mode is CameraMode.TECHNICAL:
                self._playback.overlay_mode = "TECHNICAL"
            if self._camera_director is not None:
                self._camera_director.set_mode(camera_mode)
            self._revision += 1
            self._playback_event.set()
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
            self._camera_mode = CameraMode.FREE_CAMERA
            self._playback.camera_mode = CameraMode.FREE_CAMERA
            self._revision += 1
            self._playback_event.set()
            return self.snapshot()

    def playback_control(self, payload: dict[str, object]) -> dict[str, object]:
        action = str(payload.get("action", "")).upper()
        with self._lock:
            recording = self._require_recording_locked()
            if action == "PLAY":
                if self._playback.current_time >= recording.duration_s:
                    self._playback.current_time = 0.0
                self._playback.paused = False
            elif action == "PAUSE":
                self._playback.paused = True
            elif action == "REPLAY":
                self._playback.current_time = 0.0
                self._playback.paused = False
            elif action == "SEEK":
                self._playback.current_time = float(
                    max(0.0, min(recording.duration_s, float(payload["time_s"])))
                )
            elif action in {"STEP_FORWARD", "STEP_BACKWARD"}:
                index = recording.index_at(self._playback.current_time)
                index += 1 if action == "STEP_FORWARD" else -1
                index = max(0, min(len(recording.timestamps) - 1, index))
                self._playback.current_time = float(recording.timestamps[index])
                self._playback.paused = True
            elif action == "SPEED":
                speed = float(payload["speed"])
                if speed not in _PLAYBACK_SPEEDS:
                    raise ValueError("playback speed must be 0.25, 0.5, 1, or 2")
                self._playback.playback_speed = speed
            elif action == "OVERLAY":
                self._playback.overlay_mode = (
                    "TECHNICAL" if bool(payload.get("enabled", True)) else "OFF"
                )
            else:
                raise ValueError("unsupported playback action")
            self._revision += 1
            self._playback_event.set()
            return self.snapshot()

    def open_recording(self, recording_id: str, *, saved: bool = False) -> dict[str, object]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("cannot switch recordings while physics is running")
            visualization = None if saved else next(
                (item for item in self._planning_visualizations if item.recording_id == recording_id), None
            )
            if visualization is not None:
                self._current_recording = None
                self._current_visualization = visualization
                self._request = None
                self._result = None
                self._reason = visualization.rejection_reason
                self._state = SimulationState.WAITING
                self._message = f"Planning Rejected · {visualization.rejection_reason}"
                self._frame_jpeg = bytes(visualization.preview_jpeg)
                self._frame_revision += 1
                self._revision += 1
                self._frame_condition.notify_all()
                return self.snapshot()
            recording = None if saved else next(
                (item for item in self._session_recordings if item.recording_id == recording_id), None
            )
        if recording is None:
            try:
                recording = load_recording(recording_id, self._recordings_root)
            except ValueError as dynamic_error:
                try:
                    visualization = load_planning_visualization(recording_id, self._recordings_root)
                except ValueError:
                    raise dynamic_error
                with self._lock:
                    self._planning_visualizations.append(visualization)
                    self._current_recording = None
                    self._current_visualization = visualization
                    self._request = None
                    self._result = None
                    self._reason = visualization.rejection_reason
                    self._state = SimulationState.WAITING
                    self._message = f"Planning Rejected · {visualization.rejection_reason}"
                    self._frame_jpeg = bytes(visualization.preview_jpeg)
                    self._frame_revision += 1
                    self._revision += 1
                    self._frame_condition.notify_all()
                    return self.snapshot()
            with self._lock:
                self._append_session_recording_locked(recording)
        with self._lock:
            self._activate_recording_locked(recording)
            self._playback_event.set()
            return self.snapshot()

    def save_current_recording(self) -> dict[str, object]:
        with self._lock:
            visualization = self._current_visualization
            if visualization is not None:
                if visualization.saved:
                    return self.snapshot()
                recording = None
            else:
                recording = self._require_recording_locked()
            if recording is not None and recording.saved:
                return self.snapshot()
        if visualization is not None:
            save_planning_visualization(visualization, self._recordings_root)
        else:
            assert recording is not None
            save_recording(recording, self._recordings_root)
        with self._lock:
            self._revision += 1
            return self.snapshot()

    def session_history(self) -> dict[str, object]:
        with self._lock:
            return {
                "schema_version": "gongshu.recording-history/v1",
                "session_history": [item.public_summary() for item in reversed(self._session_recordings)],
                "visualization_history": [
                    item.public_summary() for item in reversed(self._planning_visualizations)
                ],
                "saved_runs": list_saved_runs(self._recordings_root),
            }

    def record_planning_rejection(
        self, metadata: dict[str, object], preview_jpeg: bytes | None
    ) -> dict[str, object] | None:
        """Keep a non-physics rejection visualization in this process session only."""

        reason = str(metadata.get("error_code") or "NO_VALID_CANDIDATE")
        allowed = {
            "WIDTH_LIMIT",  # Legacy session/import compatibility; planner no longer emits it.
            "GRIPPER_TOO_NARROW",
            "GRIPPER_TOO_WIDE",
            "LOW_GRASP_QUALITY+GRIPPER_TOO_NARROW",
            "LOW_GRASP_QUALITY+GRIPPER_TOO_WIDE",
            "OUT_OF_REACH",
            "ABNORMAL_SCALE",
            "LOW_GEOMETRY_CONFIDENCE",
        }
        if reason not in allowed or not preview_jpeg:
            return None
        job_id = str(metadata.get("job_id") or uuid.uuid4().hex)
        recording_id = f"viz-{job_id[-16:]}"
        with self._lock:
            existing = next(
                (item for item in self._planning_visualizations if item.recording_id == recording_id), None
            )
            if existing is not None:
                return existing.public_summary()
            visualization = PlanningVisualizationRecording(
                recording_id=recording_id,
                run_id=f"rejected-{uuid.uuid4().hex[:16]}",
                created_at=utc_timestamp(),
                rejection_reason=reason,
                metadata=dict(metadata),
                preview_jpeg=bytes(preview_jpeg),
            )
            self._planning_visualizations.append(visualization)
            if len(self._planning_visualizations) > self._max_session_recordings:
                self._planning_visualizations = self._planning_visualizations[-self._max_session_recordings:]
            self._revision += 1
            return visualization.public_summary()

    def export_video(self) -> dict[str, object]:
        """Explicitly render an MP4 from the immutable recording and view settings."""

        if not self._export_lock.acquire(blocking=False):
            raise RuntimeError("a video export is already running")
        try:
            with self._lock:
                recording = self._require_recording_locked()
                mode = self._playback.camera_mode
                speed = self._playback.playback_speed
                overlay = self._playback.overlay_mode == "TECHNICAL"
                self._playback.paused = True
            root = Path(self._exports_root or default_exports_root()).resolve()
            root.mkdir(parents=True, exist_ok=True)
            destination = root / f"{recording.recording_id}-{mode.value.lower()}-{speed:g}x.mp4"
            from .native_panda_validation import CameraDirector, RecordingPlaybackRenderer

            renderer = RecordingPlaybackRenderer(recording, CameraDirector(mode))
            fps = 24.0
            writer = cv2.VideoWriter(
                str(destination), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                (renderer.width, renderer.height),
            )
            if not writer.isOpened():
                renderer.close()
                raise RuntimeError("MP4 encoder could not be opened")
            try:
                frame_count = max(1, int(recording.duration_s / speed * fps) + 1)
                for frame_index in range(frame_count):
                    source_time = min(recording.duration_s, frame_index / fps * speed)
                    jpeg, _ = renderer.render_at(source_time, technical_overlay=overlay)
                    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    writer.write(image)
            finally:
                writer.release()
                renderer.close()
            return {
                "status": "EXPORTED", "path": str(destination),
                "recording_id": recording.recording_id,
            }
        finally:
            self._export_lock.release()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            recording = self._current_recording
            visualization = self._current_visualization
            request_metadata = (
                self._request.public_metadata()
                if self._request is not None
                else (dict(recording.request_metadata) if recording is not None else None)
            )
            active_summary = (
                recording.public_summary() if recording is not None
                else (visualization.public_summary() if visualization is not None else None)
            )
            return {
                "schema_version": VALIDATION_SCHEMA_VERSION,
                "status": self._state.value,
                "message": self._message,
                "reason": self._reason,
                "revision": self._revision,
                "frame_revision": self._frame_revision,
                "camera_mode": self._camera_mode.value,
                "scenario": (
                    request_metadata.get("scene_transform", {}).get(
                        "scenario", ValidationScenario.NOMINAL.value
                    )
                    if request_metadata is not None
                    else ValidationScenario.NOMINAL.value
                ),
                "request": request_metadata,
                "planning_result": (
                    request_metadata.get("planning_result")
                    if request_metadata is not None
                    else (
                        {
                            "status": "PLANNING_REJECTED",
                            "reason": visualization.rejection_reason,
                        }
                        if visualization is not None
                        else None
                    )
                ),
                "telemetry": dict(self._telemetry),
                "state_history": [dict(item) for item in self._state_history],
                "result": None if self._result is None else self._result.public_metadata(),
                "recording": active_summary,
                "playback": None if recording is None else self._playback.public_metadata(
                    duration_s=recording.duration_s
                ),
                "history": {
                    "session_count": len(self._session_recordings),
                    "saved_count": len(list_saved_runs(self._recordings_root)),
                },
                "media": {
                    "stream_available": self._frame_jpeg is not None,
                    "replay_available": recording is not None,
                    "visualization_available": visualization is not None,
                    "recording_saved": bool(
                        (recording and recording.saved) or (visualization and visualization.saved)
                    ),
                },
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
            recording = getattr(backend, "recording", None)
            with self._lock:
                self._result = result
                self._reason = result.reason
                self._set_state_locked(
                    result.state,
                    "仿真验证成功 Simulation Validation SUCCESS" if result.succeeded
                    else f"仿真验证失败 Simulation Validation FAILED · {result.reason or 'State Error'}",
                )
                if isinstance(recording, SimulationRecording):
                    self._append_session_recording_locked(recording)
                    self._activate_recording_locked(recording, preserve_result=True)
                    self._playback.current_time = recording.duration_s
                    self._playback.paused = True
                    self._playback_event.set()
        except Exception as error:
            with self._lock:
                self._reason = str(error) or "State Error"
                self._set_state_locked(
                    SimulationState.FAILED,
                    f"仿真验证失败 Simulation Validation FAILED · {self._reason}",
                )

    def _playback_loop(self) -> None:
        renderer = None
        renderer_id = None
        last_tick = time.monotonic()
        while not self._playback_shutdown.is_set():
            signaled = self._playback_event.wait(timeout=1.0 / 24.0)
            self._playback_event.clear()
            with self._lock:
                recording = self._current_recording
                playing = recording is not None and not self._playback.paused
                now = time.monotonic()
                if playing:
                    self._playback.current_time += (now - last_tick) * self._playback.playback_speed
                    if self._playback.current_time >= recording.duration_s:
                        self._playback.current_time = recording.duration_s
                        self._playback.paused = True
                last_tick = now
                should_render = recording is not None and (
                    signaled or playing or renderer_id != recording.recording_id
                )
                timestamp = self._playback.current_time
                overlay = self._playback.overlay_mode == "TECHNICAL"
                director = self._camera_director
            if recording is None:
                if renderer is not None:
                    renderer.close()
                    renderer = None
                    renderer_id = None
                continue
            if not should_render:
                continue
            try:
                if renderer_id != recording.recording_id:
                    if renderer is not None:
                        renderer.close()
                    from .native_panda_validation import CameraDirector, RecordingPlaybackRenderer
                    if director is None:
                        director = CameraDirector(self._camera_mode)
                        with self._lock:
                            self._camera_director = director
                    renderer = RecordingPlaybackRenderer(recording, director)
                    renderer_id = recording.recording_id
                jpeg, telemetry = renderer.render_at(timestamp, technical_overlay=overlay)
                with self._frame_condition:
                    if self._current_recording is recording:
                        self._frame_jpeg = jpeg
                        self._telemetry = telemetry
                        self._frame_revision += 1
                        self._revision += 1
                        self._frame_condition.notify_all()
            except Exception as error:
                with self._lock:
                    self._reason = f"Playback render failed: {error}"
                    self._revision += 1
        if renderer is not None:
            renderer.close()

    def _on_frame(self, state: SimulationState, jpeg: bytes, telemetry: dict[str, object]) -> None:
        with self._frame_condition:
            if state not in {SimulationState.SUCCESS, SimulationState.FAILED} and self._state is not state:
                self._set_state_locked(state, f"MuJoCo · {state.value}")
            self._frame_jpeg = bytes(jpeg)
            self._telemetry = dict(telemetry)
            self._frame_revision += 1
            self._frame_condition.notify_all()

    def _append_session_recording_locked(self, recording: SimulationRecording) -> None:
        self._session_recordings = [
            item for item in self._session_recordings if item.recording_id != recording.recording_id
        ]
        self._session_recordings.append(recording)
        if len(self._session_recordings) > self._max_session_recordings:
            self._session_recordings = self._session_recordings[-self._max_session_recordings:]

    def _activate_recording_locked(
        self, recording: SimulationRecording, *, preserve_result: bool = False
    ) -> None:
        if not preserve_result:
            self._request = None
        self._current_recording = recording
        self._current_visualization = None
        self._result = recording.result
        self._reason = recording.result.reason
        self._state = recording.result.state
        self._camera_mode = CameraMode.AUTO_CINEMATIC
        self._playback = PlaybackSession(current_time=recording.duration_s)
        from .native_panda_validation import CameraDirector
        self._camera_director = CameraDirector(CameraMode.AUTO_CINEMATIC)
        if not preserve_result:
            self._message = "已打开会话 Recording" if not recording.saved else "已打开保存的 Recording"
        self._revision += 1

    def _require_recording_locked(self) -> SimulationRecording:
        if self._current_recording is None:
            raise RuntimeError("no SimulationRecording is available")
        return self._current_recording

    def _set_state_locked(self, state: SimulationState, message: str) -> None:
        if not self._state_history or self._state_history[-1]["state"] != state.value:
            elapsed = 0.0 if self._started_at <= 0.0 else time.monotonic() - self._started_at
            self._state_history.append({"state": state.value, "elapsed_s": elapsed})
        self._state = state
        self._message = message
        self._revision += 1
