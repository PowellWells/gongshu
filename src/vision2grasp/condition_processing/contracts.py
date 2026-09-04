"""Explainable visual-condition and uncertainty contracts for Gongshu experiments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
from typing import Any

import numpy as np

from vision2grasp.contracts import RGBFrame


CONDITION_REPORT_SCHEMA_VERSION = "gongshu.condition-report/v1"
CONDITION_STRESS_REPORT_SCHEMA_VERSION = "gongshu.condition-stress-report/v1"
UNCERTAINTY_SCHEMA_VERSION = "gongshu.pipeline-uncertainty/v1"


class ConditionProtocol(str, Enum):
    NORMAL = "NORMAL"
    BLUR = "BLUR"
    LOW_LIGHT = "LOW_LIGHT"
    LOW_LIGHT_BLUR = "LOW_LIGHT_BLUR"
    OCCLUSION = "OCCLUSION"


class VisualCondition(str, Enum):
    NORMAL = "NORMAL"
    BLUR = "BLUR"
    LOW_LIGHT = "LOW_LIGHT"
    LOW_LIGHT_BLUR = "LOW_LIGHT_BLUR"


class StressStrategy(str, Enum):
    STRESS_ONLY = "STRESS_ONLY"
    STRESS_PLUS_RECOVERY = "STRESS_PLUS_RECOVERY"


class StressLevel(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class StressBlurType(str, Enum):
    GAUSSIAN = "GAUSSIAN"
    MOTION = "MOTION"


class BlurLevel(str, Enum):
    CLEAR = "CLEAR"
    MILD_BLUR = "MILD_BLUR"
    MODERATE_BLUR = "MODERATE_BLUR"
    SEVERE_BLUR = "SEVERE_BLUR"


class LowLightLevel(str, Enum):
    NORMAL_LIGHT = "NORMAL_LIGHT"
    MILD_LOW_LIGHT = "MILD_LOW_LIGHT"
    MODERATE_LOW_LIGHT = "MODERATE_LOW_LIGHT"
    SEVERE_LOW_LIGHT = "SEVERE_LOW_LIGHT"


class ReliabilityLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EnhancementStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    ASSESSMENT_ONLY = "ASSESSMENT_ONLY"
    APPLIED = "APPLIED"
    REVERTED = "REVERTED"
    FAILED = "FAILED"
    PENDING_NOT_IMPLEMENTED = "PENDING_NOT_IMPLEMENTED"


@dataclass(frozen=True, slots=True)
class ConditionMetrics:
    variance_of_laplacian: float
    tenengrad: float
    edge_density: float
    mean_luminance: float
    luminance_p10: float
    luminance_p90: float
    dark_pixel_ratio: float
    clipped_highlight_ratio: float
    contrast_std: float

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = float(getattr(self, name))
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")

    def public_metadata(self) -> dict[str, float]:
        return {name: round(float(getattr(self, name)), 6) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class ConditionStressReport:
    condition: ConditionProtocol
    strategy: StressStrategy
    level: StressLevel
    blur_type: StressBlurType
    random_seed: int
    raw_frame_id: int
    degraded_frame_id: int
    enhanced_frame_id: int | None
    pipeline_frame_id: int
    raw_sha256: str
    degraded_sha256: str
    enhanced_sha256: str | None
    pipeline_sha256: str
    degradation_chain: tuple[str, ...]
    parameters: dict[str, Any]

    def __post_init__(self) -> None:
        if self.random_seed < 0:
            raise ValueError("stress random_seed must be non-negative")
        if min(self.raw_frame_id, self.degraded_frame_id, self.pipeline_frame_id) < 0:
            raise ValueError("stress frame identifiers must be non-negative")
        if self.enhanced_frame_id is not None and self.enhanced_frame_id < 0:
            raise ValueError("enhanced_frame_id must be non-negative")
        object.__setattr__(self, "degradation_chain", tuple(self.degradation_chain))
        object.__setattr__(self, "parameters", dict(self.parameters))

    @property
    def applied(self) -> bool:
        return self.degraded_frame_id != self.raw_frame_id

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": CONDITION_STRESS_REPORT_SCHEMA_VERSION,
            "condition": self.condition.value,
            "strategy": self.strategy.value,
            "level": self.level.value,
            "blur_type": self.blur_type.value,
            "random_seed": self.random_seed,
            "stress_applied": self.applied,
            "degradation_chain": list(self.degradation_chain),
            "parameters": dict(self.parameters),
            "frames": {
                "raw": {"frame_id": self.raw_frame_id, "sha256": self.raw_sha256},
                "degraded": {
                    "frame_id": self.degraded_frame_id,
                    "sha256": self.degraded_sha256,
                },
                "enhanced": (
                    None
                    if self.enhanced_frame_id is None
                    else {"frame_id": self.enhanced_frame_id, "sha256": self.enhanced_sha256}
                ),
                "pipeline": {
                    "frame_id": self.pipeline_frame_id,
                    "sha256": self.pipeline_sha256,
                },
            },
            "scope": "RESEARCH_VISUAL_INPUT_ONLY",
        }


@dataclass(frozen=True, slots=True)
class ConditionReport:
    report_id: str
    protocol: ConditionProtocol
    visual_condition: VisualCondition
    raw_frame_id: int
    processed_frame_id: int
    blur_score: float
    brightness_score: float
    blur_level: BlurLevel
    low_light_level: LowLightLevel
    image_quality_score: float
    before_quality: float
    after_quality: float
    enhancement_applied: bool
    enhancement_status: EnhancementStatus
    enhancement_method: str | None
    enhancement_chain: tuple[str, ...]
    reliability: ReliabilityLevel
    confidence_hint: str
    uncertainty_hints: tuple[str, ...]
    raw_metrics: ConditionMetrics
    processed_metrics: ConditionMetrics
    raw_sha256: str
    processed_sha256: str
    stress_test: ConditionStressReport | None = None

    def __post_init__(self) -> None:
        if not self.report_id.strip():
            raise ValueError("report_id must not be empty")
        if self.raw_frame_id < 0 or self.processed_frame_id < 0:
            raise ValueError("frame identifiers must be non-negative")
        for name in ("blur_score", "brightness_score", "image_quality_score", "before_quality", "after_quality"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.enhancement_applied != (self.enhancement_status is EnhancementStatus.APPLIED):
            raise ValueError("enhancement_applied must match enhancement_status")
        if self.enhancement_applied and self.processed_frame_id == self.raw_frame_id:
            raise ValueError("an applied enhancement requires a new processed frame id")
        if not self.enhancement_applied and self.processed_frame_id != self.raw_frame_id:
            raise ValueError("an unchanged frame must preserve its source frame id")
        object.__setattr__(self, "enhancement_chain", tuple(self.enhancement_chain))
        object.__setattr__(self, "uncertainty_hints", tuple(dict.fromkeys(self.uncertainty_hints)))

    def public_metadata(self) -> dict[str, Any]:
        stress = None if self.stress_test is None else self.stress_test.public_metadata()
        return {
            "schema_version": CONDITION_REPORT_SCHEMA_VERSION,
            "report_id": self.report_id,
            "condition_type": self.protocol.value,
            "visual_condition": self.visual_condition.value,
            "raw_frame_id": (
                self.raw_frame_id if self.stress_test is None else self.stress_test.raw_frame_id
            ),
            "condition_input_frame_id": self.raw_frame_id,
            "degraded_frame_id": (
                self.raw_frame_id
                if self.stress_test is None
                else self.stress_test.degraded_frame_id
            ),
            "enhanced_frame_id": (
                None if self.stress_test is None else self.stress_test.enhanced_frame_id
            ),
            "processed_frame_id": (
                self.processed_frame_id
                if self.stress_test is None
                else self.stress_test.pipeline_frame_id
            ),
            "blur_score": self.blur_score,
            "brightness_score": self.brightness_score,
            "blur_level": self.blur_level.value,
            "low_light_level": self.low_light_level.value,
            "image_quality_score": self.image_quality_score,
            "before_quality": self.before_quality,
            "after_quality": self.after_quality,
            "enhancement_applied": self.enhancement_applied,
            "enhancement_status": self.enhancement_status.value,
            "enhancement_method": self.enhancement_method,
            "enhancement_chain": list(self.enhancement_chain),
            "reliability": self.reliability.value,
            "confidence_hint": self.confidence_hint,
            "uncertainty_hint": list(self.uncertainty_hints),
            "raw_metrics": self.raw_metrics.public_metadata(),
            "processed_metrics": self.processed_metrics.public_metadata(),
            "raw_sha256": (
                self.raw_sha256 if self.stress_test is None else self.stress_test.raw_sha256
            ),
            "condition_input_sha256": self.raw_sha256,
            "degraded_sha256": (
                self.raw_sha256
                if self.stress_test is None
                else self.stress_test.degraded_sha256
            ),
            "processed_sha256": self.processed_sha256,
            "stress_test": stress,
            "provenance": (
                "RAW_IMMUTABLE_TO_OPTIONAL_ACCEPTED_ENHANCEMENT"
                if self.stress_test is None
                else "RAW_TO_DEGRADED_TO_OPTIONAL_ENHANCED_TO_PIPELINE"
            ),
            "extension_interfaces": {
                "occlusion_condition": "PENDING",
                "domain_shift": {
                    "camera_change": "PENDING",
                    "lighting_change": "PENDING",
                    "background_change": "PENDING",
                },
            },
        }


@dataclass(frozen=True, slots=True)
class ConditionedFrame:
    raw_frame: RGBFrame
    processed_frame: RGBFrame
    report: ConditionReport
    source_frame: RGBFrame | None = None
    degraded_frame: RGBFrame | None = None
    enhanced_frame: RGBFrame | None = None

    def __post_init__(self) -> None:
        raw_rgb = np.ascontiguousarray(self.raw_frame.rgb.copy(), dtype=np.uint8)
        processed_rgb = np.ascontiguousarray(self.processed_frame.rgb.copy(), dtype=np.uint8)
        raw_rgb.setflags(write=False)
        processed_rgb.setflags(write=False)
        raw = RGBFrame(self.raw_frame.frame_id, self.raw_frame.timestamp_s, self.raw_frame.camera_name, raw_rgb)
        processed = RGBFrame(
            self.processed_frame.frame_id,
            self.processed_frame.timestamp_s,
            self.processed_frame.camera_name,
            processed_rgb,
        )
        if raw.timestamp_s != processed.timestamp_s or raw.camera_name != processed.camera_name:
            raise ValueError("raw and processed frames must describe the same capture")
        if self.report.raw_frame_id != raw.frame_id or self.report.processed_frame_id != processed.frame_id:
            raise ValueError("ConditionReport frame provenance does not match frames")
        object.__setattr__(self, "raw_frame", raw)
        object.__setattr__(self, "processed_frame", processed)
        source_value = self.source_frame or raw
        degraded_value = self.degraded_frame or raw
        source = self._immutable_frame(source_value)
        degraded = self._immutable_frame(degraded_value)
        enhanced = None if self.enhanced_frame is None else self._immutable_frame(self.enhanced_frame)
        if source.timestamp_s != processed.timestamp_s or degraded.timestamp_s != processed.timestamp_s:
            raise ValueError("condition experiment frames must describe the same capture")
        if enhanced is not None and enhanced.timestamp_s != processed.timestamp_s:
            raise ValueError("enhanced frame must describe the same capture")
        stress = self.report.stress_test
        if stress is not None:
            if source.frame_id != stress.raw_frame_id or degraded.frame_id != stress.degraded_frame_id:
                raise ValueError("stress frame provenance does not match ConditionedFrame")
            if processed.frame_id != stress.pipeline_frame_id:
                raise ValueError("pipeline frame does not match stress provenance")
            if (enhanced is None) != (stress.enhanced_frame_id is None):
                raise ValueError("enhanced frame availability does not match stress provenance")
            if enhanced is not None and enhanced.frame_id != stress.enhanced_frame_id:
                raise ValueError("enhanced frame does not match stress provenance")
            hashes = {
                "raw": hashlib.sha256(source.rgb.tobytes()).hexdigest(),
                "degraded": hashlib.sha256(degraded.rgb.tobytes()).hexdigest(),
                "pipeline": hashlib.sha256(processed.rgb.tobytes()).hexdigest(),
            }
            if hashes["raw"] != stress.raw_sha256:
                raise ValueError("raw frame hash does not match stress provenance")
            if hashes["degraded"] != stress.degraded_sha256:
                raise ValueError("degraded frame hash does not match stress provenance")
            if hashes["pipeline"] != stress.pipeline_sha256:
                raise ValueError("pipeline frame hash does not match stress provenance")
            if enhanced is not None and hashlib.sha256(enhanced.rgb.tobytes()).hexdigest() != stress.enhanced_sha256:
                raise ValueError("enhanced frame hash does not match stress provenance")
        object.__setattr__(self, "source_frame", source)
        object.__setattr__(self, "degraded_frame", degraded)
        object.__setattr__(self, "enhanced_frame", enhanced)

    @staticmethod
    def _immutable_frame(frame: RGBFrame) -> RGBFrame:
        rgb = np.ascontiguousarray(frame.rgb.copy(), dtype=np.uint8)
        rgb.setflags(write=False)
        return RGBFrame(frame.frame_id, frame.timestamp_s, frame.camera_name, rgb)


@dataclass(frozen=True, slots=True)
class PipelineUncertainty:
    stage: str
    report_id: str
    level: ReliabilityLevel
    confidence: float | None
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.stage.strip() or not self.report_id.strip():
            raise ValueError("uncertainty stage and report id must not be empty")
        if self.confidence is not None and (
            not np.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("uncertainty confidence must be None or in [0, 1]")
        object.__setattr__(self, "reasons", tuple(dict.fromkeys(self.reasons)))

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": UNCERTAINTY_SCHEMA_VERSION,
            "stage": self.stage,
            "condition_report_id": self.report_id,
            "reliability": self.level.value,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "contract_status": "EVIDENCE_INTERFACE_V0_8",
        }


class PerceptionUncertainty(PipelineUncertainty):
    pass


class SpatialUncertainty(PipelineUncertainty):
    pass


class GraspUncertainty(PipelineUncertainty):
    pass
