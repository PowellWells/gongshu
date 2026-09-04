"""Model-neutral target-perception contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
from typing import Any

import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import RGBFrame
from vision2grasp.condition_processing import ConditionReport, PerceptionUncertainty


UNKNOWN_TARGET_LABEL = "未知目标 Unknown Object"


@dataclass(frozen=True, slots=True)
class TargetLockMetadata:
    """Small, replay-safe record of the user's target selection."""

    frame_id: int
    selected_bbox_xyxy: tuple[float, float, float, float]
    target_id: str
    lock_timestamp: str

    def __post_init__(self) -> None:
        if self.frame_id < 0:
            raise ValueError("target lock frame_id must be non-negative")
        if not self.target_id.strip():
            raise ValueError("target lock target_id must not be empty")
        x1, y1, x2, y2 = self.selected_bbox_xyxy
        if not all(np.isfinite(value) for value in self.selected_bbox_xyxy):
            raise ValueError("target lock bbox must contain only finite values")
        if x2 <= x1 or y2 <= y1:
            raise ValueError("target lock bbox must have positive width and height")
        try:
            datetime.fromisoformat(self.lock_timestamp)
        except ValueError as error:
            raise ValueError("target lock timestamp must be ISO-8601") from error

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": "gongshu.target-lock-metadata/v1",
            "frame_id": self.frame_id,
            "selected_bbox": [round(value, 2) for value in self.selected_bbox_xyxy],
            "target_id": self.target_id,
            "lock_timestamp": self.lock_timestamp,
        }


@dataclass(frozen=True, slots=True)
class TargetInstance:
    """One selectable instance region tied to an immutable source RGB frame.

    Instance geometry is mandatory. Semantic class information and confidence
    are optional and must never decide whether the target is selectable.
    """

    instance_id: str
    mask: NDArray[np.bool_]
    bbox_xyxy: tuple[float, float, float, float]
    centroid_2d: tuple[float, float]
    source_frame_id: int
    source_timestamp_s: float
    confidence: float | None = None
    class_name: str | None = None
    semantic_source: str | None = None

    def __post_init__(self) -> None:
        instance_id = self.instance_id.strip()
        if not instance_id:
            raise ValueError("instance_id must not be empty")
        object.__setattr__(self, "instance_id", instance_id)
        if self.mask.ndim != 2 or self.mask.dtype != np.bool_:
            raise ValueError("mask must be a 2D boolean array")
        if not np.any(self.mask):
            raise ValueError("mask must contain at least one target pixel")
        immutable_mask = np.ascontiguousarray(self.mask.copy(), dtype=np.bool_)
        immutable_mask.setflags(write=False)
        object.__setattr__(self, "mask", immutable_mask)
        height, width = immutable_mask.shape
        x1, y1, x2, y2 = self.bbox_xyxy
        if not all(np.isfinite(value) for value in self.bbox_xyxy):
            raise ValueError("bbox_xyxy must contain only finite values")
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bbox_xyxy must have positive width and height")
        if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
            raise ValueError("bbox_xyxy must stay inside the source frame")
        centroid_x, centroid_y = self.centroid_2d
        if not np.isfinite(centroid_x) or not np.isfinite(centroid_y):
            raise ValueError("centroid_2d must contain only finite values")
        if not 0 <= centroid_x < width or not 0 <= centroid_y < height:
            raise ValueError("centroid_2d must stay inside the source frame")
        if self.source_frame_id < 0:
            raise ValueError("source_frame_id must be non-negative")
        if not np.isfinite(self.source_timestamp_s):
            raise ValueError("source_timestamp_s must be finite")
        if self.confidence is not None:
            if not np.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
                raise ValueError("confidence must be None or between 0 and 1")
        normalized_class = (self.class_name or "").strip() or UNKNOWN_TARGET_LABEL
        object.__setattr__(self, "class_name", normalized_class)
        normalized_source = (self.semantic_source or "").strip() or None
        object.__setattr__(self, "semantic_source", normalized_source)

    @property
    def selectable(self) -> bool:
        """Every valid geometric instance is selectable, including unknowns."""

        return True

    def public_metadata(self, *, selected: bool) -> dict[str, object]:
        """Return compact UI metadata without exposing the full mask tensor."""

        return {
            "id": self.instance_id,
            "bbox_xyxy": [round(value, 2) for value in self.bbox_xyxy],
            "centroid_2d": [round(value, 2) for value in self.centroid_2d],
            "source_frame_id": self.source_frame_id,
            "source_timestamp_s": self.source_timestamp_s,
            "confidence": self.confidence,
            "class_name": self.class_name,
            "semantic_source": self.semantic_source,
            "selectable": True,
            "state": "LOCKED" if selected else "SELECTABLE",
        }


@dataclass(frozen=True, slots=True)
class TargetSceneSnapshot:
    """One selected target and its immutable source RGB frame association."""

    snapshot_id: str
    frame: RGBFrame
    target: TargetInstance
    raw_frame: RGBFrame | None = None
    degraded_frame: RGBFrame | None = None
    enhanced_frame: RGBFrame | None = None
    condition_report: ConditionReport | None = None
    perception_uncertainty: PerceptionUncertainty | None = None
    target_lock_metadata: TargetLockMetadata | None = None

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be empty")
        immutable_rgb = np.ascontiguousarray(self.frame.rgb.copy(), dtype=np.uint8)
        immutable_rgb.setflags(write=False)
        immutable_frame = RGBFrame(
            frame_id=self.frame.frame_id,
            timestamp_s=self.frame.timestamp_s,
            camera_name=self.frame.camera_name,
            rgb=immutable_rgb,
        )
        object.__setattr__(self, "frame", immutable_frame)
        raw_source = self.raw_frame or self.frame
        raw_rgb = np.ascontiguousarray(raw_source.rgb.copy(), dtype=np.uint8)
        raw_rgb.setflags(write=False)
        immutable_raw = RGBFrame(
            frame_id=raw_source.frame_id,
            timestamp_s=raw_source.timestamp_s,
            camera_name=raw_source.camera_name,
            rgb=raw_rgb,
        )
        object.__setattr__(self, "raw_frame", immutable_raw)
        degraded_source = self.degraded_frame or self.frame
        degraded_rgb = np.ascontiguousarray(degraded_source.rgb.copy(), dtype=np.uint8)
        degraded_rgb.setflags(write=False)
        immutable_degraded = RGBFrame(
            degraded_source.frame_id,
            degraded_source.timestamp_s,
            degraded_source.camera_name,
            degraded_rgb,
        )
        object.__setattr__(self, "degraded_frame", immutable_degraded)
        if self.enhanced_frame is not None:
            enhanced_rgb = np.ascontiguousarray(self.enhanced_frame.rgb.copy(), dtype=np.uint8)
            enhanced_rgb.setflags(write=False)
            object.__setattr__(
                self,
                "enhanced_frame",
                RGBFrame(
                    self.enhanced_frame.frame_id,
                    self.enhanced_frame.timestamp_s,
                    self.enhanced_frame.camera_name,
                    enhanced_rgb,
                ),
            )
        if self.target.source_frame_id != self.frame.frame_id:
            raise ValueError("target source_frame_id does not match snapshot frame")
        if self.target.source_timestamp_s != self.frame.timestamp_s:
            raise ValueError("target timestamp does not match snapshot frame")
        if self.target.mask.shape != self.frame.rgb.shape[:2]:
            raise ValueError("target mask does not match snapshot frame")
        if self.target_lock_metadata is not None:
            if self.target_lock_metadata.frame_id != self.frame.frame_id:
                raise ValueError("target lock frame does not match snapshot frame")
            if self.target_lock_metadata.target_id != self.target.instance_id:
                raise ValueError("target lock id does not match snapshot target")
        if immutable_raw.timestamp_s != self.frame.timestamp_s:
            raise ValueError("raw and processed snapshot timestamps do not match")
        if self.condition_report is not None:
            stress = self.condition_report.stress_test
            expected_raw_id = (
                self.condition_report.raw_frame_id if stress is None else stress.raw_frame_id
            )
            if expected_raw_id != immutable_raw.frame_id:
                raise ValueError("ConditionReport raw frame does not match snapshot")
            expected_pipeline_id = (
                self.condition_report.processed_frame_id
                if stress is None
                else stress.pipeline_frame_id
            )
            if expected_pipeline_id != self.frame.frame_id:
                raise ValueError("ConditionReport processed frame does not match snapshot")
            if stress is not None and stress.degraded_frame_id != immutable_degraded.frame_id:
                raise ValueError("ConditionReport degraded frame does not match snapshot")

    def public_metadata(self) -> dict[str, object]:
        height, width = self.frame.rgb.shape[:2]
        return {
            "available": True,
            "snapshot_id": self.snapshot_id,
            "geometry_chain_id": self.geometry_chain_id,
            "source_frame_id": self.frame.frame_id,
            "raw_frame_id": self.raw_frame.frame_id,
            "processed_frame_id": self.frame.frame_id,
            "degraded_frame_id": self.degraded_frame.frame_id,
            "enhanced_frame_id": (
                None if self.enhanced_frame is None else self.enhanced_frame.frame_id
            ),
            "source_timestamp_s": self.frame.timestamp_s,
            "target_id": self.target.instance_id,
            "snapshot_size": {"width": width, "height": height},
            "mask_size": {"width": self.target.mask.shape[1], "height": self.target.mask.shape[0]},
            "condition_report": (
                None if self.condition_report is None else self.condition_report.public_metadata()
            ),
            "perception_uncertainty": (
                None
                if self.perception_uncertainty is None
                else self.perception_uncertainty.public_metadata()
            ),
            "target_lock_metadata": (
                None
                if self.target_lock_metadata is None
                else self.target_lock_metadata.public_metadata()
            ),
        }

    @property
    def geometry_chain_id(self) -> str:
        """Stable identity for RGB, mask, depth, intrinsics, and derived XYZ."""

        height, width = self.frame.rgb.shape[:2]
        payload = "|".join(
            (
                self.snapshot_id,
                str(self.frame.frame_id),
                str(self.raw_frame.frame_id),
                repr(self.frame.timestamp_s),
                self.target.instance_id,
                "none" if self.condition_report is None else self.condition_report.report_id,
                f"{width}x{height}",
            )
        ).encode("utf-8")
        return f"geometry-{hashlib.sha256(payload).hexdigest()[:24]}"
