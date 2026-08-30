"""Thread-safe frozen-snapshot spatial analysis state."""

from __future__ import annotations

import threading
import time
from typing import Final

from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import SpatialObservation, SpatialStage
from .interfaces import SpatialPerceptionProvider
from .monocular import DepthUnavailableError
from .visualization import encode_jpeg, render_spatial_overview


SPATIAL_PERCEPTION_SCHEMA_VERSION: Final = "gongshu.spatial-perception/v1"

_STAGE_MESSAGES: Final = {
    SpatialStage.SCENE_PREPARING: "正在准备场景 Scene Preparing...",
    SpatialStage.MODEL_LOADING: "正在加载深度模型 Model Loading...",
    SpatialStage.DEPTH_ESTIMATING: "正在估计深度 Depth Estimating...",
    SpatialStage.POINT_CLOUD_BUILDING: "正在生成目标点云 Point Cloud Building...",
    SpatialStage.SPATIAL_COMPUTING: "正在计算空间位置 Spatial Computing...",
    SpatialStage.READY: "空间感知完成 SPATIAL READY",
    SpatialStage.ERROR: "空间分析失败 SPATIAL ERROR",
}


class SpatialPerceptionService:
    def __init__(self, provider: SpatialPerceptionProvider) -> None:
        self._provider = provider
        self._lock = threading.RLock()
        self._analysis_guard = threading.Lock()
        self._status = "IDLE"
        self._message = "等待空间分析 WAITING"
        self._error_code: str | None = None
        self._revision = 0
        self._observation: SpatialObservation | None = None
        self._overview_jpeg: bytes | None = None
        self._scene_snapshot: dict[str, object] | None = None
        self._stage: SpatialStage | None = None
        self._failed_stage: SpatialStage | None = None
        self._analysis_started_at: float | None = None
        self._completed_total_s: float | None = None
        self._timing: dict[str, object] = {}
        self._model_state = "NOT_LOADED"

    def analyze(
        self,
        snapshot: TargetSceneSnapshot,
        *,
        expected_snapshot_id: str,
        expected_source_frame_id: int,
        expected_target_instance_id: str,
        expected_source_timestamp_s: float,
    ) -> dict[str, object]:
        if not self._analysis_guard.acquire(blocking=False):
            raise RuntimeError("spatial analysis is already running")
        try:
            analysis_started = time.perf_counter()
            with self._lock:
                self._status = "ANALYZING"
                self._stage = SpatialStage.SCENE_PREPARING
                self._failed_stage = None
                self._message = _STAGE_MESSAGES[self._stage]
                self._error_code = None
                self._observation = None
                self._overview_jpeg = None
                self._scene_snapshot = snapshot.public_metadata()
                self._analysis_started_at = analysis_started
                self._completed_total_s = None
                self._timing = {}
                self._revision += 1
            self._validate_expected_association(
                snapshot,
                expected_snapshot_id=expected_snapshot_id,
                expected_source_frame_id=expected_source_frame_id,
                expected_target_instance_id=expected_target_instance_id,
                expected_source_timestamp_s=expected_source_timestamp_s,
            )
            observation = self._provider.analyze(snapshot, self._report_progress)
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
            overview = encode_jpeg(render_spatial_overview(observation, snapshot))
            total_s = time.perf_counter() - analysis_started
            with self._lock:
                self._observation = observation
                self._overview_jpeg = overview
                self._status = "READY"
                self._stage = SpatialStage.READY
                self._message = _STAGE_MESSAGES[self._stage]
                self._error_code = None
                self._completed_total_s = total_s
                self._timing.update(
                    {
                        "model_load_s": observation.depth_frame.model_load_time_s,
                        "depth_inference_s": observation.depth_frame.inference_time_s,
                        "model_was_ready": observation.depth_frame.model_was_ready,
                        "model_location": observation.depth_frame.model_location,
                    }
                )
                consumed = sum(
                    float(self._timing.get(key, 0.0))
                    for key in ("model_load_s", "depth_inference_s", "point_cloud_s")
                )
                self._timing["spatial_computing_s"] = max(total_s - consumed, 0.0)
                self._model_state = "READY"
                self._revision += 1
                return self.snapshot()
        except Exception as error:
            total_s = time.perf_counter() - (
                self._analysis_started_at or time.perf_counter()
            )
            with self._lock:
                self._status = "ERROR"
                self._message = str(error) or "空间分析失败 SPATIAL ERROR"
                self._error_code = self._classify_error(error)
                self._failed_stage = self._stage
                self._stage = SpatialStage.ERROR
                self._observation = None
                self._overview_jpeg = None
                self._completed_total_s = max(total_s, 0.0)
                self._revision += 1
                return self.snapshot()
        finally:
            self._analysis_guard.release()

    def reset(self) -> dict[str, object]:
        if self._analysis_guard.locked():
            raise RuntimeError("cannot reset while spatial analysis is running")
        with self._lock:
            self._status = "IDLE"
            self._message = "等待空间分析 WAITING"
            self._error_code = None
            self._observation = None
            self._overview_jpeg = None
            self._scene_snapshot = None
            self._stage = None
            self._failed_stage = None
            self._analysis_started_at = None
            self._completed_total_s = None
            self._timing = {}
            self._revision += 1
            return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            if self._completed_total_s is not None:
                elapsed_s = self._completed_total_s
            elif self._analysis_started_at is not None:
                elapsed_s = max(time.perf_counter() - self._analysis_started_at, 0.0)
            else:
                elapsed_s = 0.0
            return {
                "schema_version": SPATIAL_PERCEPTION_SCHEMA_VERSION,
                "status": self._status,
                "message": self._message,
                "error_code": self._error_code,
                "stage": None if self._stage is None else self._stage.value,
                "stage_message": (
                    None if self._stage is None else _STAGE_MESSAGES[self._stage]
                ),
                "failed_stage": (
                    None if self._failed_stage is None else self._failed_stage.value
                ),
                "revision": self._revision,
                "model_state": self._model_state,
                "timing": {
                    **self._timing,
                    "elapsed_s": elapsed_s,
                    "total_s": self._completed_total_s,
                },
                "scene_snapshot": (
                    None if self._scene_snapshot is None else dict(self._scene_snapshot)
                ),
                "observation": (
                    None if self._observation is None else self._observation.public_metadata()
                ),
                "media": {
                    "overview_available": self._overview_jpeg is not None,
                },
            }

    def _report_progress(
        self,
        stage: SpatialStage,
        details: object = None,
    ) -> None:
        with self._lock:
            if self._status != "ANALYZING":
                return
            self._stage = stage
            self._message = _STAGE_MESSAGES[stage]
            if isinstance(details, dict):
                self._timing.update(details)
                if details.get("model_state") == "READY":
                    self._model_state = "READY"
            if stage is SpatialStage.MODEL_LOADING:
                self._model_state = "LOADING"
            self._revision += 1

    def overview_jpeg(self) -> bytes | None:
        with self._lock:
            return None if self._overview_jpeg is None else bytes(self._overview_jpeg)

    def current_observation(self) -> SpatialObservation:
        """Return the immutable READY observation for downstream contracts."""

        with self._lock:
            if self._status != "READY" or self._observation is None:
                raise RuntimeError("SpatialObservation is not ready")
            return self._observation

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
    def _classify_error(error: Exception) -> str:
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
