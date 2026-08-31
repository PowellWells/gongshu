"""Asynchronous, snapshot-bound Spatial jobs with stale-result protection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import threading
import time
from typing import Final
from uuid import uuid4

from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import SpatialObservation, SpatialStage
from .depth_worker import SpatialWatchdogConfig
from .interfaces import SpatialPerceptionProvider
from .monocular import DepthUnavailableError
from .timing_history import SpatialTimingHistory, TimingProfile
from .visualization import encode_jpeg, render_spatial_overview


SPATIAL_PERCEPTION_SCHEMA_VERSION: Final = "gongshu.spatial-perception/v2"

_STAGE_MESSAGES: Final = {
    SpatialStage.QUEUED: "等待后台执行 Queued...",
    SpatialStage.SCENE_PREPARING: "正在准备场景 Scene Preparing...",
    SpatialStage.MODEL_RESOLVING: "正在解析深度模型 Model Resolving...",
    SpatialStage.MODEL_DOWNLOADING: "正在下载深度模型 Model Downloading...",
    SpatialStage.CHECKSUM_VERIFYING: "正在校验模型 Checksum Verifying...",
    SpatialStage.MODEL_LOADING: "正在加载深度模型 Model Loading...",
    SpatialStage.DEPTH_INFERENCE: "正在估计深度 Depth Estimating...",
    SpatialStage.POINT_CLOUD_BUILDING: "正在生成目标点云 Point Cloud Building...",
    SpatialStage.SPATIAL_COMPUTING: "正在计算空间位置 Spatial Computing...",
    SpatialStage.READY: "空间感知完成 SPATIAL READY",
    SpatialStage.FAILED: "空间分析失败 SPATIAL FAILED",
    SpatialStage.CANCELLED: "空间任务已取消 Spatial Job Cancelled",
}


class SpatialJobCancelled(RuntimeError):
    code = "SPATIAL_JOB_CANCELLED"


@dataclass(slots=True)
class _SpatialJob:
    job_id: str
    snapshot: TargetSceneSnapshot
    cancel_event: threading.Event
    created_at: float
    started_monotonic: float
    cold_start: bool
    stage: SpatialStage = SpatialStage.QUEUED
    stage_started_at: float = field(default_factory=time.time)
    stage_started_monotonic: float = field(default_factory=time.monotonic)
    last_heartbeat_at: float = field(default_factory=time.time)
    stage_durations: dict[str, float] = field(default_factory=dict)
    timing: dict[str, object] = field(default_factory=dict)
    taking_longer: bool = False
    thread: threading.Thread | None = None


class SpatialPerceptionService:
    def __init__(
        self,
        provider: SpatialPerceptionProvider,
        *,
        watchdog: SpatialWatchdogConfig | None = None,
        timing_history: SpatialTimingHistory | None = None,
        benchmark_path: Path | None = None,
        compute_device: str = "cpu",
        input_size: int = 518,
    ) -> None:
        self._provider = provider
        self._watchdog = watchdog or SpatialWatchdogConfig()
        self._timing_history = timing_history or SpatialTimingHistory(
            benchmark_path=benchmark_path,
            persistent=benchmark_path is not None,
        )
        self._compute_device = compute_device
        self._input_size = input_size
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._status = "IDLE"
        self._message = "等待空间分析 WAITING"
        self._error_code: str | None = None
        self._revision = 0
        self._observation: SpatialObservation | None = None
        self._overview_jpeg: bytes | None = None
        self._scene_snapshot: dict[str, object] | None = None
        self._failed_stage: SpatialStage | None = None
        self._completed_total_s: float | None = None
        self._model_state = "NOT_LOADED"
        self._current_job: _SpatialJob | None = None
        self._cancelled_jobs: list[dict[str, object]] = []

    def start(
        self,
        snapshot: TargetSceneSnapshot,
        *,
        expected_snapshot_id: str,
        expected_source_frame_id: int,
        expected_target_instance_id: str,
        expected_source_timestamp_s: float,
    ) -> dict[str, object]:
        self._validate_expected_association(
            snapshot,
            expected_snapshot_id=expected_snapshot_id,
            expected_source_frame_id=expected_source_frame_id,
            expected_target_instance_id=expected_target_instance_id,
            expected_source_timestamp_s=expected_source_timestamp_s,
        )
        self._supersede_current("SUPERSEDED")
        now = time.time()
        job = _SpatialJob(
            job_id=f"spatial-{uuid4().hex}",
            snapshot=snapshot,
            cancel_event=threading.Event(),
            created_at=now,
            started_monotonic=time.monotonic(),
            cold_start=not self._provider_model_ready(),
            stage_started_at=now,
            stage_started_monotonic=time.monotonic(),
            last_heartbeat_at=now,
        )
        with self._lock:
            self._current_job = job
            self._status = "QUEUED"
            self._message = _STAGE_MESSAGES[SpatialStage.QUEUED]
            self._error_code = None
            self._observation = None
            self._overview_jpeg = None
            self._scene_snapshot = snapshot.public_metadata()
            self._failed_stage = None
            self._completed_total_s = None
            self._revision += 1
            thread = threading.Thread(
                target=self._run_job,
                args=(job,),
                name=f"gongshu-{job.job_id}",
                daemon=True,
            )
            job.thread = thread
            thread.start()
            threading.Thread(
                target=self._watch_job,
                args=(job,),
                name=f"gongshu-watchdog-{job.job_id}",
                daemon=True,
            ).start()
            return self.snapshot()

    def analyze(
        self,
        snapshot: TargetSceneSnapshot,
        *,
        expected_snapshot_id: str,
        expected_source_frame_id: int,
        expected_target_instance_id: str,
        expected_source_timestamp_s: float,
    ) -> dict[str, object]:
        """Compatibility wrapper for tests and non-HTTP callers."""

        try:
            initial = self.start(
                snapshot,
                expected_snapshot_id=expected_snapshot_id,
                expected_source_frame_id=expected_source_frame_id,
                expected_target_instance_id=expected_target_instance_id,
                expected_source_timestamp_s=expected_source_timestamp_s,
            )
        except Exception as error:
            with self._lock:
                self._status = "FAILED"
                self._message = str(error)
                self._error_code = self._classify_error(error)
                self._failed_stage = SpatialStage.SCENE_PREPARING
                self._completed_total_s = 0.0
                self._observation = None
                self._overview_jpeg = None
                self._current_job = None
                self._revision += 1
                return self.snapshot()
        return self.wait(str(initial["job_id"]), timeout_s=180.0)

    def wait(self, job_id: str, *, timeout_s: float) -> dict[str, object]:
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while True:
                state = self.snapshot()
                if state.get("job_id") != job_id:
                    return state
                if state["status"] in {"READY", "FAILED", "CANCELLED"}:
                    return state
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise TimeoutError(f"spatial job did not finish: {job_id}")
                self._condition.wait(timeout=min(remaining, 0.25))

    def retry(self) -> dict[str, object]:
        with self._lock:
            job = self._current_job
            if job is None:
                raise RuntimeError("no Spatial Job is available to retry")
            snapshot = job.snapshot
        return self.start(
            snapshot,
            expected_snapshot_id=snapshot.snapshot_id,
            expected_source_frame_id=snapshot.frame.frame_id,
            expected_target_instance_id=snapshot.target.instance_id,
            expected_source_timestamp_s=snapshot.frame.timestamp_s,
        )

    def reset(self) -> dict[str, object]:
        self._supersede_current("CANCELLED")
        with self._lock:
            self._status = "IDLE"
            self._message = "等待空间分析 WAITING"
            self._error_code = None
            self._observation = None
            self._overview_jpeg = None
            self._scene_snapshot = None
            self._failed_stage = None
            self._completed_total_s = None
            self._current_job = None
            self._revision += 1
            self._condition.notify_all()
            return self.snapshot()

    def close(self) -> None:
        self._supersede_current("CANCELLED")
        close = getattr(self._provider, "close", None)
        if callable(close):
            close()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            job = self._current_job
            if job is None:
                elapsed_s = 0.0
                stage_elapsed_s = 0.0
                stage = None
                timing: dict[str, object] = {}
                job_id = None
                heartbeat = None
                binding = None
                taking_longer = False
                eta: dict[str, object] = {
                    "available": False,
                    "source": "ESTIMATING",
                }
            else:
                now_mono = time.monotonic()
                elapsed_s = (
                    self._completed_total_s
                    if self._completed_total_s is not None
                    else max(now_mono - job.started_monotonic, 0.0)
                )
                stage_elapsed_s = max(now_mono - job.stage_started_monotonic, 0.0)
                stage = job.stage
                timing = dict(job.timing)
                job_id = job.job_id
                heartbeat = job.last_heartbeat_at
                binding = {
                    "job_id": job.job_id,
                    "snapshot_id": job.snapshot.snapshot_id,
                    "source_frame_id": job.snapshot.frame.frame_id,
                    "target_instance_id": job.snapshot.target.instance_id,
                    "source_timestamp_s": job.snapshot.frame.timestamp_s,
                    "geometry_chain_id": job.snapshot.geometry_chain_id,
                }
                eta = self._timing_history.estimate(
                    self._profile(job),
                    stage=job.stage.value,
                    stage_elapsed_s=stage_elapsed_s,
                    total_elapsed_s=elapsed_s,
                )
                typical = eta.get("stage_typical_range_s")
                history_slow = (
                    isinstance(typical, list)
                    and len(typical) == 2
                    and stage_elapsed_s > float(typical[1])
                )
                taking_longer = job.taking_longer or history_slow
            return {
                "schema_version": SPATIAL_PERCEPTION_SCHEMA_VERSION,
                "job_id": job_id,
                "status": self._status,
                "message": self._message,
                "error_code": self._error_code,
                "stage": None if stage is None else stage.value,
                "stage_message": None if stage is None else _STAGE_MESSAGES[stage],
                "stage_started_at": None if job is None else job.stage_started_at,
                "stage_elapsed_s": stage_elapsed_s,
                "total_elapsed_s": elapsed_s,
                "last_heartbeat_at": heartbeat,
                "taking_longer": taking_longer,
                "failed_stage": (
                    None if self._failed_stage is None else self._failed_stage.value
                ),
                "revision": self._revision,
                "model_state": self._model_state,
                "cold_start": None if job is None else job.cold_start,
                "timing": {
                    **timing,
                    "elapsed_s": elapsed_s,
                    "stage_elapsed_s": stage_elapsed_s,
                    "total_s": self._completed_total_s,
                    "stage_durations_s": (
                        {} if job is None else dict(job.stage_durations)
                    ),
                },
                "eta": eta,
                "download": None if job is None else self._download_state(job),
                "resolver_diagnostics": (
                    [] if job is None else list(job.timing.get("resolver_diagnostics", []))
                ),
                "binding": binding,
                "cancelled_jobs": list(self._cancelled_jobs[-8:]),
                "scene_snapshot": (
                    None if self._scene_snapshot is None else dict(self._scene_snapshot)
                ),
                "observation": (
                    None if self._observation is None else self._observation.public_metadata()
                ),
                "media": {"overview_available": self._overview_jpeg is not None},
            }

    def overview_jpeg(self) -> bytes | None:
        with self._lock:
            return None if self._overview_jpeg is None else bytes(self._overview_jpeg)

    def current_observation(self) -> SpatialObservation:
        with self._lock:
            if self._status != "READY" or self._observation is None:
                raise RuntimeError("SpatialObservation is not ready")
            return self._observation

    def _run_job(self, job: _SpatialJob) -> None:
        try:
            observation = self._provider.analyze(
                job.snapshot,
                lambda stage, details=None: self._report_progress(job, stage, details),
            )
            self._validate_observation(job.snapshot, observation)
            overview = encode_jpeg(render_spatial_overview(observation, job.snapshot))
            total_s = time.monotonic() - job.started_monotonic
            with self._lock:
                self._require_current(job)
                self._finish_stage(job)
                self._observation = observation
                self._overview_jpeg = overview
                self._status = "READY"
                self._transition(job, SpatialStage.READY)
                self._message = _STAGE_MESSAGES[SpatialStage.READY]
                self._error_code = None
                self._completed_total_s = total_s
                job.timing.update(
                    {
                        "model_load_s": observation.depth_frame.model_load_time_s,
                        "depth_inference_s": observation.depth_frame.inference_time_s,
                        "model_was_ready": observation.depth_frame.model_was_ready,
                        "model_location": observation.depth_frame.model_location,
                        "spatial_computing_s": job.stage_durations.get(
                            SpatialStage.SPATIAL_COMPUTING.value,
                            0.0,
                        ),
                    }
                )
                self._model_state = "READY"
                self._revision += 1
                self._condition.notify_all()
            self._timing_history.add_success(
                self._profile(job), job.stage_durations, total_s
            )
        except SpatialJobCancelled:
            with self._lock:
                if self._is_current(job) and self._status == "FAILED":
                    return
            self._record_cancelled(job, "CANCELLED")
        except BaseException as error:
            with self._lock:
                if not self._is_current(job) or job.cancel_event.is_set():
                    self._record_cancelled_locked(job, "SUPERSEDED")
                    return
                self._finish_stage(job)
                self._failed_stage = job.stage
                self._status = "FAILED"
                self._transition(job, SpatialStage.FAILED)
                self._message = str(error) or _STAGE_MESSAGES[SpatialStage.FAILED]
                self._error_code = self._classify_error(error)
                self._observation = None
                self._overview_jpeg = None
                self._completed_total_s = max(
                    time.monotonic() - job.started_monotonic, 0.0
                )
                self._revision += 1
                self._condition.notify_all()

    def _report_progress(
        self,
        job: _SpatialJob,
        stage: SpatialStage,
        details: object,
    ) -> None:
        with self._lock:
            self._require_current(job)
            if stage is not job.stage:
                self._finish_stage(job)
                self._transition(job, stage)
            job.last_heartbeat_at = time.time()
            if isinstance(details, dict):
                job.timing.update(details)
                if details.get("model_state") == "READY":
                    self._model_state = "READY"
                if details.get("taking_longer"):
                    job.taking_longer = True
                diagnostic = details.get("resolver_diagnostic")
                if isinstance(diagnostic, dict):
                    existing = list(job.timing.get("resolver_diagnostics", []))
                    existing.append(dict(diagnostic))
                    job.timing["resolver_diagnostics"] = existing
            if stage is SpatialStage.MODEL_LOADING:
                self._model_state = "LOADING"
            self._status = "ANALYZING"
            self._message = _STAGE_MESSAGES[stage]
            self._revision += 1
            self._condition.notify_all()

    def _watch_job(self, job: _SpatialJob) -> None:
        while not job.cancel_event.wait(self._watchdog.heartbeat_interval_s):
            with self._lock:
                if not self._is_current(job) or self._status in {
                    "READY",
                    "FAILED",
                    "CANCELLED",
                }:
                    return
                job.last_heartbeat_at = time.time()
                elapsed = time.monotonic() - job.stage_started_monotonic
                if job.stage in {
                    SpatialStage.POINT_CLOUD_BUILDING,
                    SpatialStage.SPATIAL_COMPUTING,
                }:
                    warning_s = (
                        self._watchdog.point_cloud_warning_s
                        if job.stage is SpatialStage.POINT_CLOUD_BUILDING
                        else self._watchdog.spatial_computing_warning_s
                    )
                    timeout_s = (
                        self._watchdog.point_cloud_timeout_s
                        if job.stage is SpatialStage.POINT_CLOUD_BUILDING
                        else self._watchdog.spatial_computing_timeout_s
                    )
                    if elapsed >= warning_s:
                        job.taking_longer = True
                    if elapsed >= timeout_s:
                        job.cancel_event.set()
                        self._failed_stage = job.stage
                        self._status = "FAILED"
                        self._error_code = (
                            "POINT_CLOUD_TIMEOUT"
                            if job.stage is SpatialStage.POINT_CLOUD_BUILDING
                            else "SPATIAL_COMPUTE_TIMEOUT"
                        )
                        self._message = (
                            f"{self._error_code}: {job.stage.value} exceeded "
                            f"{timeout_s:.1f} s"
                        )
                        self._transition(job, SpatialStage.FAILED)
                        self._completed_total_s = time.monotonic() - job.started_monotonic
                        self._revision += 1
                        self._condition.notify_all()
                        return
                self._revision += 1
                self._condition.notify_all()

    def _supersede_current(self, reason: str) -> None:
        with self._lock:
            job = self._current_job
            if job is None or self._status in {"READY", "FAILED", "CANCELLED", "IDLE"}:
                return
            job.cancel_event.set()
            self._record_cancelled_locked(job, reason)
        cancel = getattr(self._provider, "cancel_current", None)
        if callable(cancel):
            cancel()

    def _record_cancelled(self, job: _SpatialJob, reason: str) -> None:
        with self._lock:
            self._record_cancelled_locked(job, reason)

    def _record_cancelled_locked(self, job: _SpatialJob, reason: str) -> None:
        if any(item["job_id"] == job.job_id for item in self._cancelled_jobs):
            return
        self._cancelled_jobs.append(
            {
                "job_id": job.job_id,
                "status": "CANCELLED",
                "reason": reason,
                "snapshot_id": job.snapshot.snapshot_id,
                "source_frame_id": job.snapshot.frame.frame_id,
                "target_instance_id": job.snapshot.target.instance_id,
                "cancelled_at": time.time(),
            }
        )
        if self._is_current(job) and reason == "CANCELLED":
            self._status = "CANCELLED"
            self._transition(job, SpatialStage.CANCELLED)
            self._message = _STAGE_MESSAGES[SpatialStage.CANCELLED]
            self._error_code = "SPATIAL_JOB_CANCELLED"
            self._completed_total_s = time.monotonic() - job.started_monotonic
        self._revision += 1
        self._condition.notify_all()

    def _transition(self, job: _SpatialJob, stage: SpatialStage) -> None:
        job.stage = stage
        job.stage_started_at = time.time()
        job.stage_started_monotonic = time.monotonic()
        job.last_heartbeat_at = time.time()
        job.taking_longer = False

    @staticmethod
    def _finish_stage(job: _SpatialJob) -> None:
        if job.stage in {SpatialStage.READY, SpatialStage.FAILED, SpatialStage.CANCELLED}:
            return
        job.stage_durations[job.stage.value] = max(
            time.monotonic() - job.stage_started_monotonic, 0.0
        )

    def _require_current(self, job: _SpatialJob) -> None:
        if not self._is_current(job) or job.cancel_event.is_set():
            raise SpatialJobCancelled("Spatial Job was cancelled or superseded")

    def _is_current(self, job: _SpatialJob) -> bool:
        return self._current_job is job

    def _provider_model_ready(self) -> bool:
        return bool(getattr(self._provider, "model_ready", False))

    def _profile(self, job: _SpatialJob) -> TimingProfile:
        return TimingProfile(
            model="depth-anything-v2-metric-indoor-small",
            compute_device=self._compute_device,
            input_size=self._input_size,
            cold_start=job.cold_start,
        )

    @staticmethod
    def _download_state(job: _SpatialJob) -> dict[str, object] | None:
        if "bytes_downloaded" not in job.timing:
            return None
        return {
            key: job.timing.get(key)
            for key in (
                "bytes_downloaded",
                "bytes_total",
                "download_progress",
                "download_speed_bytes_s",
                "download_eta_s",
            )
        }

    @staticmethod
    def _validate_observation(
        snapshot: TargetSceneSnapshot,
        observation: SpatialObservation,
    ) -> None:
        if observation.snapshot_id != snapshot.snapshot_id:
            raise ValueError("SpatialObservation snapshot association mismatch")
        if observation.source_frame_id != snapshot.frame.frame_id:
            raise ValueError("SpatialObservation frame mismatch")
        if observation.target_instance_id != snapshot.target.instance_id:
            raise ValueError("SpatialObservation target mismatch")
        if observation.source_timestamp_s != snapshot.frame.timestamp_s:
            raise ValueError("SpatialObservation timestamp mismatch")
        if observation.geometry_chain_id != snapshot.geometry_chain_id:
            raise ValueError("SpatialObservation geometry transform chain mismatch")

    @staticmethod
    def _validate_expected_association(
        snapshot: TargetSceneSnapshot,
        *,
        expected_snapshot_id: str,
        expected_source_frame_id: int,
        expected_target_instance_id: str,
        expected_source_timestamp_s: float,
    ) -> None:
        if expected_snapshot_id != snapshot.snapshot_id:
            raise ValueError("Scene Snapshot association mismatch")
        if expected_source_frame_id != snapshot.frame.frame_id:
            raise ValueError("Scene Snapshot frame mismatch")
        if expected_target_instance_id != snapshot.target.instance_id:
            raise ValueError("Scene Snapshot target mismatch")
        if expected_source_timestamp_s != snapshot.frame.timestamp_s:
            raise ValueError("Scene Snapshot timestamp mismatch")

    @staticmethod
    def _classify_error(error: BaseException) -> str:
        code = getattr(error, "code", None)
        if isinstance(code, str) and code:
            return code
        if isinstance(error, DepthUnavailableError):
            return "DEPTH_UNAVAILABLE"
        message = str(error).lower()
        if "mask is empty" in message:
            return "TARGET_MASK_EMPTY"
        if "below minimum" in message:
            return "TOO_FEW_VALID_DEPTH_PIXELS"
        if "intrinsics" in message:
            return "INVALID_INTRINSICS"
        if "point cloud" in message:
            return "POINT_CLOUD_EMPTY"
        if "target" in message:
            return "TARGET_MISMATCH"
        if "frame" in message or "snapshot" in message or "timestamp" in message:
            return "FRAME_MISMATCH"
        if "depth" in message:
            return "DEPTH_UNAVAILABLE"
        return "SPATIAL_ANALYSIS_FAILED"
