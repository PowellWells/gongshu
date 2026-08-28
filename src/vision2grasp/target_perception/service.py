"""Frozen-frame target analysis and manual selection state."""

from __future__ import annotations

import threading
from typing import Final

from vision2grasp.contracts import RGBFrame

from .contracts import TargetInstance
from .interfaces import TargetInstanceSegmenter
from .visualization import encode_jpeg, render_target_overlay


TARGET_PERCEPTION_SCHEMA_VERSION: Final = "gongshu.target-perception/v1"


class TargetPerceptionService:
    """Own one immutable analysis frame and its selectable target instances."""

    def __init__(self, segmenter: TargetInstanceSegmenter) -> None:
        self._segmenter = segmenter
        self._lock = threading.RLock()
        self._analysis_guard = threading.Lock()
        self._status = "IDLE"
        self._message = "等待目标分析 WAITING"
        self._revision = 0
        self._frame: RGBFrame | None = None
        self._instances: tuple[TargetInstance, ...] = ()
        self._selected_target_id: str | None = None
        self._overlay_jpeg: bytes | None = None
        self._snapshot_jpeg: bytes | None = None

    def analyze(self, frame: RGBFrame) -> dict[str, object]:
        if not self._analysis_guard.acquire(blocking=False):
            raise RuntimeError("target analysis is already running")
        frozen_frame = RGBFrame(
            frame_id=frame.frame_id,
            timestamp_s=frame.timestamp_s,
            camera_name=frame.camera_name,
            rgb=frame.rgb.copy(),
        )
        try:
            with self._lock:
                self._status = "ANALYZING"
                self._message = "正在分析目标 Target Perception"
                self._frame = frozen_frame
                self._instances = ()
                self._selected_target_id = None
                self._overlay_jpeg = None
                self._snapshot_jpeg = encode_jpeg(frozen_frame.rgb)
                self._revision += 1
            instances = tuple(self._segmenter.predict(frozen_frame))
            for instance in instances:
                if instance.source_frame_id != frozen_frame.frame_id:
                    raise ValueError("TargetInstance source_frame_id does not match analysis frame")
                if instance.source_timestamp_s != frozen_frame.timestamp_s:
                    raise ValueError("TargetInstance timestamp does not match analysis frame")
                if instance.mask.shape != frozen_frame.rgb.shape[:2]:
                    raise ValueError("TargetInstance mask does not match analysis frame")
            overlay = render_target_overlay(
                frozen_frame,
                instances,
                selected_target_id=None,
            )
            with self._lock:
                self._instances = instances
                self._status = "CANDIDATES" if instances else "NO_CANDIDATES"
                self._message = (
                    f"发现 {len(instances)} 个可选目标 Object Candidates"
                    if instances
                    else "未发现有效目标候选 NO CANDIDATES"
                )
                self._overlay_jpeg = encode_jpeg(overlay)
                self._revision += 1
                return self.snapshot()
        except Exception as error:
            with self._lock:
                self._status = "ERROR"
                self._message = str(error)
                self._instances = ()
                self._selected_target_id = None
                self._overlay_jpeg = None
                self._revision += 1
            raise
        finally:
            self._analysis_guard.release()

    def select(self, target_id: str, *, source_frame_id: int) -> dict[str, object]:
        with self._lock:
            if self._frame is None or self._status not in {"CANDIDATES", "TARGET_LOCKED"}:
                raise RuntimeError("no target candidates are available")
            if source_frame_id != self._frame.frame_id:
                raise ValueError("target selection frame does not match frozen analysis frame")
            selected = next(
                (instance for instance in self._instances if instance.instance_id == target_id),
                None,
            )
            if selected is None:
                raise ValueError(f"unknown target candidate: {target_id}")
            self._selected_target_id = selected.instance_id
            self._status = "TARGET_LOCKED"
            self._message = "目标已锁定 TARGET LOCKED"
            overlay = render_target_overlay(
                self._frame,
                self._instances,
                selected_target_id=selected.instance_id,
            )
            self._overlay_jpeg = encode_jpeg(overlay)
            self._revision += 1
            return self.snapshot()

    def reset(self) -> dict[str, object]:
        with self._lock:
            if self._analysis_guard.locked():
                raise RuntimeError("cannot reset while target analysis is running")
            self._status = "IDLE"
            self._message = "等待目标分析 WAITING"
            self._frame = None
            self._instances = ()
            self._selected_target_id = None
            self._overlay_jpeg = None
            self._snapshot_jpeg = None
            self._revision += 1
            return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            selected = self.selected_instance()
            frame = self._frame
            return {
                "schema_version": TARGET_PERCEPTION_SCHEMA_VERSION,
                "status": self._status,
                "message": self._message,
                "revision": self._revision,
                "frame": (
                    None
                    if frame is None
                    else {
                        "id": frame.frame_id,
                        "timestamp_s": frame.timestamp_s,
                        "camera_name": frame.camera_name,
                        "width": int(frame.rgb.shape[1]),
                        "height": int(frame.rgb.shape[0]),
                    }
                ),
                "candidates": [
                    instance.public_metadata(selected=instance.instance_id == self._selected_target_id)
                    for instance in self._instances
                ],
                "selected_target_id": self._selected_target_id,
                "selected_target": (
                    None if selected is None else selected.public_metadata(selected=True)
                ),
                "scene_snapshot": (
                    None
                    if selected is None or frame is None
                    else {
                        "available": True,
                        "source_frame_id": frame.frame_id,
                        "source_timestamp_s": frame.timestamp_s,
                        "target_id": selected.instance_id,
                    }
                ),
            }

    def selected_instance(self) -> TargetInstance | None:
        with self._lock:
            if self._selected_target_id is None:
                return None
            return next(
                (
                    instance
                    for instance in self._instances
                    if instance.instance_id == self._selected_target_id
                ),
                None,
            )

    def overlay_jpeg(self) -> bytes | None:
        with self._lock:
            return None if self._overlay_jpeg is None else bytes(self._overlay_jpeg)

    def scene_snapshot_jpeg(self) -> bytes | None:
        with self._lock:
            if self._selected_target_id is None or self._snapshot_jpeg is None:
                return None
            return bytes(self._snapshot_jpeg)
