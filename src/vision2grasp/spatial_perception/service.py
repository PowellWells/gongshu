"""Thread-safe frozen-snapshot spatial analysis state."""

from __future__ import annotations

import threading
from typing import Final

from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import SpatialObservation
from .interfaces import SpatialPerceptionProvider
from .monocular import DepthUnavailableError
from .visualization import encode_jpeg, render_spatial_overview


SPATIAL_PERCEPTION_SCHEMA_VERSION: Final = "gongshu.spatial-perception/v1"


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
            with self._lock:
                self._status = "ANALYZING"
                self._message = "正在估计深度与空间结构 Spatial Analysis"
                self._error_code = None
                self._observation = None
                self._overview_jpeg = None
                self._scene_snapshot = snapshot.public_metadata()
                self._revision += 1
            self._validate_expected_association(
                snapshot,
                expected_snapshot_id=expected_snapshot_id,
                expected_source_frame_id=expected_source_frame_id,
                expected_target_instance_id=expected_target_instance_id,
                expected_source_timestamp_s=expected_source_timestamp_s,
            )
            observation = self._provider.analyze(snapshot)
            if observation.snapshot_id != snapshot.snapshot_id:
                raise ValueError("SpatialObservation snapshot association mismatch")
            if observation.source_frame_id != snapshot.frame.frame_id:
                raise ValueError("SpatialObservation frame mismatch")
            if observation.target_instance_id != snapshot.target.instance_id:
                raise ValueError("SpatialObservation target mismatch")
            if observation.source_timestamp_s != snapshot.frame.timestamp_s:
                raise ValueError("SpatialObservation timestamp mismatch")
            overview = encode_jpeg(render_spatial_overview(observation, snapshot))
            with self._lock:
                self._observation = observation
                self._overview_jpeg = overview
                self._status = "READY"
                self._message = "空间感知完成 SPATIAL READY"
                self._error_code = None
                self._revision += 1
                return self.snapshot()
        except Exception as error:
            with self._lock:
                self._status = "ERROR"
                self._message = str(error) or "空间分析失败 SPATIAL ERROR"
                self._error_code = self._classify_error(error)
                self._observation = None
                self._overview_jpeg = None
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
            self._revision += 1
            return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "schema_version": SPATIAL_PERCEPTION_SCHEMA_VERSION,
                "status": self._status,
                "message": self._message,
                "error_code": self._error_code,
                "revision": self._revision,
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

    def overview_jpeg(self) -> bytes | None:
        with self._lock:
            return None if self._overview_jpeg is None else bytes(self._overview_jpeg)

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
