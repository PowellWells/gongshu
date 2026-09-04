"""Frozen-frame target analysis and manual selection state."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import math
import threading
from typing import Final

import cv2
import numpy as np

from vision2grasp.contracts import RGBFrame
from vision2grasp.condition_processing import (
    ConditionedFrame,
    PerceptionUncertainty,
    ReliabilityLevel,
)

from .contracts import TargetInstance, TargetLockMetadata, TargetSceneSnapshot
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
        self._error_code: str | None = None
        self._revision = 0
        self._frame: RGBFrame | None = None
        self._conditioned_frame: ConditionedFrame | None = None
        self._perception_uncertainty: PerceptionUncertainty | None = None
        self._instances: tuple[TargetInstance, ...] = ()
        self._selected_target_id: str | None = None
        self._overlay_jpeg: bytes | None = None
        self._snapshot_jpeg: bytes | None = None
        self._condition_jpegs: dict[str, bytes] = {}
        self._target_lock_metadata: TargetLockMetadata | None = None
        self._tracking_frame: RGBFrame | None = None
        self._tracking_bbox: tuple[float, float, float, float] | None = None
        self._tracking_polygon: tuple[tuple[float, float], ...] = ()
        self._tracking_template: np.ndarray | None = None
        self._tracking_scale = 1.0
        self._bbox_history: deque[dict[str, object]] = deque(maxlen=32)

    def analyze(self, frame: RGBFrame | ConditionedFrame) -> dict[str, object]:
        if not self._analysis_guard.acquire(blocking=False):
            raise RuntimeError("target analysis is already running")
        source = frame.processed_frame if isinstance(frame, ConditionedFrame) else frame
        frozen_frame = RGBFrame(
            frame_id=source.frame_id,
            timestamp_s=source.timestamp_s,
            camera_name=source.camera_name,
            rgb=source.rgb.copy(),
        )
        try:
            with self._lock:
                had_selectable_candidates = bool(self._instances) and self._selected_target_id is None
                if not had_selectable_candidates:
                    self._status = "ANALYZING"
                    self._message = "扫描中 Scanning"
                    self._error_code = None
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
                # A click may lock the previously displayed candidates while
                # this new inference is running. Never overwrite that lock.
                if self._selected_target_id is not None:
                    return self.snapshot()
                conditioned_frame = frame if isinstance(frame, ConditionedFrame) else None
                perception_uncertainty = None
                if conditioned_frame is not None:
                    report = conditioned_frame.report
                    reasons = list(report.uncertainty_hints)
                    if report.reliability is ReliabilityLevel.LOW and "PERCEPTION_UNCERTAIN" not in reasons:
                        reasons.append("PERCEPTION_UNCERTAIN")
                    confidences = [item.confidence for item in instances if item.confidence is not None]
                    perception_uncertainty = PerceptionUncertainty(
                        stage="TARGET_PERCEPTION",
                        report_id=report.report_id,
                        level=report.reliability,
                        confidence=(None if not confidences else float(max(confidences))),
                        reasons=tuple(reasons),
                    )
                self._frame = frozen_frame
                self._conditioned_frame = conditioned_frame
                self._perception_uncertainty = perception_uncertainty
                self._instances = instances
                self._selected_target_id = None
                self._status = "CANDIDATES" if instances else "NO_CANDIDATES"
                self._message = (
                    f"发现 {len(instances)} 个可选目标 Object Candidates"
                    if instances
                    else "未发现有效目标候选 No Candidates"
                )
                self._error_code = None
                self._overlay_jpeg = encode_jpeg(overlay)
                self._snapshot_jpeg = encode_jpeg(frozen_frame.rgb)
                self._condition_jpegs = self._encode_condition_frames(frame, frozen_frame)
                self._clear_tracking_locked()
                self._revision += 1
                return self.snapshot()
        except Exception as error:
            with self._lock:
                if not self._instances and self._selected_target_id is None:
                    self._status = "ERROR"
                    self._message = str(error)
                    self._error_code = getattr(error, "code", "TARGET_PERCEPTION_FAILED")
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
            self._message = "目标已锁定 Target Locked"
            self._target_lock_metadata = TargetLockMetadata(
                frame_id=self._frame.frame_id,
                selected_bbox_xyxy=selected.bbox_xyxy,
                target_id=selected.instance_id,
                lock_timestamp=datetime.now(timezone.utc).astimezone().isoformat(
                    timespec="milliseconds"
                ),
            )
            self._tracking_frame = self._frame
            self._tracking_bbox = selected.bbox_xyxy
            self._tracking_polygon = self._mask_polygon(selected.mask)
            self._tracking_template, self._tracking_scale = self._make_tracking_template(
                self._frame, selected.bbox_xyxy
            )
            self._bbox_history.clear()
            self._append_bbox_history_locked(self._frame.frame_id, selected.bbox_xyxy)
            overlay = render_target_overlay(
                self._frame,
                self._instances,
                selected_target_id=selected.instance_id,
            )
            self._overlay_jpeg = encode_jpeg(overlay)
            self._revision += 1
            return self.snapshot()

    def track(self, frame: RGBFrame) -> dict[str, object]:
        """Cheap short-horizon bbox tracking for the live demo overlay.

        The locked Scene Snapshot remains immutable. Tracking only moves the
        high-resolution display overlay and never changes Depth or Grasp input.
        """

        with self._lock:
            selected = self.selected_instance()
            source = self._frame
            previous_bbox = self._tracking_bbox
            template = self._tracking_template
            scale = self._tracking_scale
            if (
                selected is None
                or source is None
                or previous_bbox is None
                or template is None
                or self._status != "TARGET_LOCKED"
            ):
                raise RuntimeError("no locked target is available for tracking")
            if frame.rgb.shape[:2] != source.rgb.shape[:2]:
                self._message = "目标已锁定 Target Locked"
                return self.snapshot()

        tracked_bbox = self._track_template(frame, previous_bbox, template, scale)
        with self._lock:
            if self._selected_target_id != selected.instance_id:
                return self.snapshot()
            if tracked_bbox is not None:
                old_x1, old_y1, _old_x2, _old_y2 = selected.bbox_xyxy
                new_x1, new_y1, _new_x2, _new_y2 = tracked_bbox
                dx, dy = new_x1 - old_x1, new_y1 - old_y1
                height, width = frame.rgb.shape[:2]
                self._tracking_bbox = tracked_bbox
                self._tracking_polygon = tuple(
                    (
                        float(np.clip(x + dx, 0.0, width - 1.0)),
                        float(np.clip(y + dy, 0.0, height - 1.0)),
                    )
                    for x, y in self._mask_polygon(selected.mask)
                )
                self._append_bbox_history_locked(frame.frame_id, tracked_bbox)
            self._tracking_frame = frame
            self._message = "目标跟踪 Tracking"
            self._revision += 1
            return self.snapshot()

    def select_at(
        self,
        *,
        source_x: float,
        source_y: float,
        source_frame_id: int,
    ) -> dict[str, object]:
        """Resolve a user click against frozen instance masks, then select it.

        Candidates are tested in reverse render order so overlapping masks use
        the instance visually painted on top. This is still an explicit user
        selection and never falls back to an arbitrary or largest candidate.
        """

        if not math.isfinite(source_x) or not math.isfinite(source_y):
            raise ValueError("target click coordinates must be finite")
        with self._lock:
            frame = self._frame
            if frame is None or self._status not in {"CANDIDATES", "TARGET_LOCKED"}:
                raise RuntimeError("no target candidates are available")
            if source_frame_id != frame.frame_id:
                raise ValueError("target selection frame does not match frozen analysis frame")
            height, width = frame.rgb.shape[:2]
            if not 0.0 <= source_x < width or not 0.0 <= source_y < height:
                raise ValueError("target click is outside the frozen source frame")
            pixel_x = int(source_x)
            pixel_y = int(source_y)
            hit = next(
                (
                    instance
                    for instance in reversed(self._instances)
                    if bool(instance.mask[pixel_y, pixel_x])
                ),
                None,
            )
            if hit is None:
                raise ValueError("target click did not hit an instance mask")
            target_id = hit.instance_id
        return self.select(target_id, source_frame_id=source_frame_id)

    def reset(self) -> dict[str, object]:
        with self._lock:
            if self._analysis_guard.locked():
                raise RuntimeError("cannot reset while target analysis is running")
            self._status = "IDLE"
            self._message = "等待目标分析 WAITING"
            self._error_code = None
            self._frame = None
            self._conditioned_frame = None
            self._perception_uncertainty = None
            self._instances = ()
            self._selected_target_id = None
            self._overlay_jpeg = None
            self._snapshot_jpeg = None
            self._condition_jpegs = {}
            self._clear_tracking_locked()
            self._revision += 1
            return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            selected = self.selected_instance()
            frame = self._frame
            overlay_frame = self._tracking_frame or frame
            return {
                "schema_version": TARGET_PERCEPTION_SCHEMA_VERSION,
                "status": self._status,
                "message": self._message,
                "error_code": self._error_code,
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
                "overlay_frame": (
                    None
                    if overlay_frame is None
                    else {
                        "id": overlay_frame.frame_id,
                        "timestamp_s": overlay_frame.timestamp_s,
                        "camera_name": overlay_frame.camera_name,
                        "width": int(overlay_frame.rgb.shape[1]),
                        "height": int(overlay_frame.rgb.shape[0]),
                    }
                ),
                "condition_report": (
                    None
                    if self._conditioned_frame is None
                    else self._conditioned_frame.report.public_metadata()
                ),
                "perception_uncertainty": (
                    None
                    if self._perception_uncertainty is None
                    else self._perception_uncertainty.public_metadata()
                ),
                "candidates": [self._instance_metadata(instance) for instance in self._instances],
                "selected_target_id": self._selected_target_id,
                "selected_target": (
                    None if selected is None else selected.public_metadata(selected=True)
                ),
                "scene_snapshot": (
                    None
                    if selected is None or frame is None
                    else self._make_scene_snapshot(frame, selected).public_metadata()
                ),
                "tracking": self._tracking_metadata_locked(),
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

    def condition_frame_jpeg(self, kind: str) -> bytes | None:
        """Return an immutable experiment frame preview for Raw/Processed comparison."""

        with self._lock:
            payload = self._condition_jpegs.get(kind.strip().lower())
            return None if payload is None else bytes(payload)

    def selected_scene_snapshot(self) -> TargetSceneSnapshot:
        """Return a copy of the exact frozen RGB frame associated with selection."""

        with self._lock:
            frame = self._frame
            selected = self.selected_instance()
            if frame is None or selected is None or self._status != "TARGET_LOCKED":
                raise RuntimeError("no locked target Scene Snapshot is available")
            frozen_copy = RGBFrame(
                frame_id=frame.frame_id,
                timestamp_s=frame.timestamp_s,
                camera_name=frame.camera_name,
                rgb=frame.rgb.copy(),
            )
            return self._make_scene_snapshot(frozen_copy, selected)

    def _make_scene_snapshot(
        self, frame: RGBFrame, selected: TargetInstance
    ) -> TargetSceneSnapshot:
        timestamp_us = int(round(frame.timestamp_s * 1_000_000.0))
        return TargetSceneSnapshot(
            snapshot_id=(
                f"snapshot-{frame.frame_id}-{timestamp_us}-{selected.instance_id}"
            ),
            frame=frame,
            target=selected,
            raw_frame=(
                frame
                if self._conditioned_frame is None
                else self._conditioned_frame.source_frame
            ),
            degraded_frame=(
                frame
                if self._conditioned_frame is None
                else self._conditioned_frame.degraded_frame
            ),
            enhanced_frame=(
                None
                if self._conditioned_frame is None
                else self._conditioned_frame.enhanced_frame
            ),
            condition_report=(
                None
                if self._conditioned_frame is None
                else self._conditioned_frame.report
            ),
            perception_uncertainty=self._perception_uncertainty,
            target_lock_metadata=self._target_lock_metadata,
        )

    def _instance_metadata(self, instance: TargetInstance) -> dict[str, object]:
        metadata = instance.public_metadata(
            selected=instance.instance_id == self._selected_target_id
        )
        metadata["mask_polygon"] = [
            [round(x, 2), round(y, 2)] for x, y in self._mask_polygon(instance.mask)
        ]
        return metadata

    def _tracking_metadata_locked(self) -> dict[str, object] | None:
        if (
            self._selected_target_id is None
            or self._tracking_frame is None
            or self._tracking_bbox is None
        ):
            return None
        return {
            "state": "TRACKING",
            "label": "目标跟踪 Tracking",
            "target_id": self._selected_target_id,
            "frame_id": self._tracking_frame.frame_id,
            "bbox_xyxy": [round(value, 2) for value in self._tracking_bbox],
            "mask_polygon": [
                [round(x, 2), round(y, 2)] for x, y in self._tracking_polygon
            ],
            "bbox_history_count": len(self._bbox_history),
        }

    def _clear_tracking_locked(self) -> None:
        self._target_lock_metadata = None
        self._tracking_frame = None
        self._tracking_bbox = None
        self._tracking_polygon = ()
        self._tracking_template = None
        self._tracking_scale = 1.0
        self._bbox_history.clear()

    def _append_bbox_history_locked(
        self, frame_id: int, bbox: tuple[float, float, float, float]
    ) -> None:
        self._bbox_history.append(
            {
                "frame_id": frame_id,
                "bbox_xyxy": [round(value, 2) for value in bbox],
            }
        )

    @staticmethod
    def _mask_polygon(mask: np.ndarray) -> tuple[tuple[float, float], ...]:
        contours, _hierarchy = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return ()
        contour = max(contours, key=cv2.contourArea)
        perimeter = cv2.arcLength(contour, True)
        approximated = cv2.approxPolyDP(contour, max(1.0, perimeter * 0.008), True)
        points = approximated.reshape(-1, 2)
        if len(points) > 80:
            points = points[:: math.ceil(len(points) / 80)]
        return tuple((float(x), float(y)) for x, y in points)

    @staticmethod
    def _make_tracking_template(
        frame: RGBFrame, bbox: tuple[float, float, float, float]
    ) -> tuple[np.ndarray, float]:
        height, width = frame.rgb.shape[:2]
        scale = min(1.0, 640.0 / max(height, width))
        gray = cv2.cvtColor(frame.rgb, cv2.COLOR_RGB2GRAY)
        if scale < 1.0:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        x1, y1, x2, y2 = bbox
        sx1 = max(0, int(math.floor(x1 * scale)))
        sy1 = max(0, int(math.floor(y1 * scale)))
        sx2 = min(gray.shape[1], int(math.ceil(x2 * scale)))
        sy2 = min(gray.shape[0], int(math.ceil(y2 * scale)))
        template = np.ascontiguousarray(gray[sy1:sy2, sx1:sx2])
        if template.shape[0] < 4 or template.shape[1] < 4:
            raise ValueError("selected target is too small for live tracking")
        return template, scale

    @staticmethod
    def _track_template(
        frame: RGBFrame,
        previous_bbox: tuple[float, float, float, float],
        template: np.ndarray,
        scale: float,
    ) -> tuple[float, float, float, float] | None:
        gray = cv2.cvtColor(frame.rgb, cv2.COLOR_RGB2GRAY)
        if scale < 1.0:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        x1, y1, x2, y2 = previous_bbox
        width = x2 - x1
        height = y2 - y1
        margin_x = max(24.0 / scale, width * 0.45)
        margin_y = max(24.0 / scale, height * 0.45)
        sx1 = max(0, int(math.floor((x1 - margin_x) * scale)))
        sy1 = max(0, int(math.floor((y1 - margin_y) * scale)))
        sx2 = min(gray.shape[1], int(math.ceil((x2 + margin_x) * scale)))
        sy2 = min(gray.shape[0], int(math.ceil((y2 + margin_y) * scale)))
        search = gray[sy1:sy2, sx1:sx2]
        if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
            return None
        method = cv2.TM_CCOEFF_NORMED if float(np.std(template)) >= 2.0 else cv2.TM_SQDIFF_NORMED
        result = cv2.matchTemplate(search, template, method)
        min_value, max_value, min_location, max_location = cv2.minMaxLoc(result)
        location = max_location if method == cv2.TM_CCOEFF_NORMED else min_location
        quality = max_value if method == cv2.TM_CCOEFF_NORMED else 1.0 - min_value
        if not math.isfinite(quality) or quality < 0.12:
            return None
        detected_x1 = (sx1 + location[0]) / scale
        detected_y1 = (sy1 + location[1]) / scale
        smoothed_x1 = x1 * 0.32 + detected_x1 * 0.68
        smoothed_y1 = y1 * 0.32 + detected_y1 * 0.68
        max_x1 = frame.rgb.shape[1] - width
        max_y1 = frame.rgb.shape[0] - height
        smoothed_x1 = float(np.clip(smoothed_x1, 0.0, max_x1))
        smoothed_y1 = float(np.clip(smoothed_y1, 0.0, max_y1))
        return (
            smoothed_x1,
            smoothed_y1,
            smoothed_x1 + width,
            smoothed_y1 + height,
        )

    @staticmethod
    def _encode_condition_frames(
        value: RGBFrame | ConditionedFrame, processed: RGBFrame
    ) -> dict[str, bytes]:
        if not isinstance(value, ConditionedFrame):
            payload = encode_jpeg(processed.rgb)
            return {"raw": payload, "degraded": payload, "pipeline": payload}
        frames = {
            "raw": value.source_frame,
            "degraded": value.degraded_frame,
            "pipeline": value.processed_frame,
        }
        if value.enhanced_frame is not None:
            frames["enhanced"] = value.enhanced_frame
        return {name: encode_jpeg(frame.rgb) for name, frame in frames.items()}
