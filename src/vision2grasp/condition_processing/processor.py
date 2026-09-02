"""Classical, explainable visual-condition assessment and guarded enhancement."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

import cv2
import numpy as np

from vision2grasp.contracts import RGBFrame

from .contracts import (
    BlurLevel,
    ConditionMetrics,
    ConditionProtocol,
    ConditionReport,
    ConditionedFrame,
    EnhancementStatus,
    LowLightLevel,
    ReliabilityLevel,
    VisualCondition,
)


@dataclass(frozen=True, slots=True)
class ConditionProcessingConfig:
    blur_mild_score: float = 0.35
    blur_moderate_score: float = 0.55
    blur_severe_score: float = 0.75
    low_light_mild_score: float = 0.62
    low_light_moderate_score: float = 0.42
    low_light_severe_score: float = 0.25
    low_quality_score: float = 0.45
    medium_quality_score: float = 0.70
    minimum_quality_gain: float = 0.01
    maximum_highlight_increase: float = 0.08

    def __post_init__(self) -> None:
        values = tuple(float(getattr(self, name)) for name in self.__dataclass_fields__)
        if not all(np.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
            raise ValueError("condition processing thresholds must be finite and in [0, 1]")
        if not self.blur_mild_score < self.blur_moderate_score < self.blur_severe_score:
            raise ValueError("blur score thresholds must be strictly increasing")
        if not self.low_light_severe_score < self.low_light_moderate_score < self.low_light_mild_score:
            raise ValueError("low-light score thresholds must be strictly increasing")
        if not self.low_quality_score < self.medium_quality_score:
            raise ValueError("quality reliability thresholds must be ordered")


class ConditionProcessor:
    """Assess every frame and enhance only the condition selected as protocol.

    The selector is an experimental processing protocol. It never synthesizes
    blur, darkness, or any other degradation.
    """

    def __init__(self, config: ConditionProcessingConfig | None = None) -> None:
        self.config = config or ConditionProcessingConfig()

    def process(self, frame: RGBFrame, protocol: ConditionProtocol | str = ConditionProtocol.NORMAL) -> ConditionedFrame:
        selected = protocol if isinstance(protocol, ConditionProtocol) else ConditionProtocol(str(protocol).upper().replace("-", "_"))
        raw_rgb = np.ascontiguousarray(frame.rgb.copy(), dtype=np.uint8)
        raw_metrics = self._metrics(raw_rgb)
        before = self._assessment(raw_metrics)
        candidate = raw_rgb
        chain: tuple[str, ...] = ()
        method: str | None = None
        status = EnhancementStatus.ASSESSMENT_ONLY if selected is ConditionProtocol.NORMAL else EnhancementStatus.NOT_REQUIRED

        if selected is ConditionProtocol.OCCLUSION:
            status = EnhancementStatus.PENDING_NOT_IMPLEMENTED
        elif selected is not ConditionProtocol.NORMAL:
            candidate, chain, method = self._enhance(raw_rgb, selected, before)

        accepted = False
        processed_metrics = raw_metrics
        after = before
        if chain:
            processed_metrics = self._metrics(candidate)
            after = self._assessment(processed_metrics)
            quality_gain = after["quality"] - before["quality"]
            highlight_increase = processed_metrics.clipped_highlight_ratio - raw_metrics.clipped_highlight_ratio
            accepted = quality_gain >= self.config.minimum_quality_gain and highlight_increase <= self.config.maximum_highlight_increase
            if accepted:
                status = EnhancementStatus.APPLIED
            else:
                candidate = raw_rgb
                processed_metrics = raw_metrics
                after = before
                status = EnhancementStatus.REVERTED

        raw_hash = hashlib.sha256(raw_rgb.tobytes()).hexdigest()
        processed_hash = hashlib.sha256(candidate.tobytes()).hexdigest()
        processed_id = frame.frame_id
        if accepted:
            seed = f"{frame.frame_id}|{frame.timestamp_s!r}|{selected.value}|{processed_hash}".encode()
            processed_id = int.from_bytes(hashlib.sha256(seed).digest()[:6], "big")
            if processed_id == frame.frame_id:
                processed_id = (processed_id + 1) % (2**48)
        hints = self._uncertainty_hints(after)
        report_id = f"condition-{frame.frame_id}-{hashlib.sha256((selected.value + raw_hash).encode()).hexdigest()[:16]}"
        report = ConditionReport(
            report_id=report_id,
            protocol=selected,
            visual_condition=self._visual_condition(before),
            raw_frame_id=frame.frame_id,
            processed_frame_id=processed_id,
            blur_score=round(float(after["blur_score"]), 6),
            brightness_score=round(float(after["brightness_score"]), 6),
            blur_level=after["blur_level"],
            low_light_level=after["low_light_level"],
            image_quality_score=round(float(after["quality"]), 6),
            before_quality=round(float(before["quality"]), 6),
            after_quality=round(float(after["quality"]), 6),
            enhancement_applied=accepted,
            enhancement_status=status,
            enhancement_method=method,
            enhancement_chain=chain,
            reliability=self._reliability(after["quality"]),
            confidence_hint=self._reliability(after["quality"]).value,
            uncertainty_hints=hints,
            raw_metrics=raw_metrics,
            processed_metrics=processed_metrics,
            raw_sha256=raw_hash,
            processed_sha256=processed_hash,
        )
        raw_frame = RGBFrame(frame.frame_id, frame.timestamp_s, frame.camera_name, raw_rgb)
        processed_frame = RGBFrame(processed_id, frame.timestamp_s, frame.camera_name, candidate)
        return ConditionedFrame(raw_frame, processed_frame, report)

    @staticmethod
    def _metrics(rgb: np.ndarray) -> ConditionMetrics:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        height, width = gray.shape
        scale = min(1.0, 640.0 / max(height, width))
        if scale < 1.0:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        gray_f = gray.astype(np.float32)
        # Estimate sharpness on locally normalized luminance so low exposure is
        # not automatically mislabeled as optical blur. Brightness metrics
        # below deliberately remain on the untouched grayscale observation.
        sharp_input = gray
        if int(np.max(gray)) - int(np.min(gray)) >= 8:
            sharp_input = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
        sharp_gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(sharp_input)
        sharp_f = sharp_gray.astype(np.float32)
        laplacian = cv2.Laplacian(sharp_f, cv2.CV_32F)
        gx = cv2.Sobel(sharp_f, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(sharp_f, cv2.CV_32F, 0, 1, ksize=3)
        gradient = cv2.magnitude(gx, gy)
        edges = cv2.Canny(sharp_gray, 60, 160)
        return ConditionMetrics(
            variance_of_laplacian=float(np.var(laplacian)),
            tenengrad=float(np.mean(gradient * gradient)),
            edge_density=float(np.mean(edges > 0)),
            mean_luminance=float(np.mean(gray_f)),
            luminance_p10=float(np.percentile(gray_f, 10)),
            luminance_p90=float(np.percentile(gray_f, 90)),
            dark_pixel_ratio=float(np.mean(gray < 40)),
            clipped_highlight_ratio=float(np.mean(gray > 248)),
            contrast_std=float(np.std(gray_f)),
        )

    def _assessment(self, metrics: ConditionMetrics) -> dict[str, object]:
        lap = self._normalize(metrics.variance_of_laplacian, 20.0, 500.0)
        ten = self._normalize(metrics.tenengrad, 120.0, 5000.0)
        edge = self._normalize(metrics.edge_density, 0.015, 0.18)
        sharpness = 0.45 * lap + 0.35 * ten + 0.20 * edge
        blur_score = 1.0 - sharpness
        luminance = self._normalize(metrics.mean_luminance, 25.0, 135.0)
        shadows = 1.0 - min(1.0, metrics.dark_pixel_ratio / 0.75)
        contrast = self._normalize(metrics.contrast_std, 10.0, 55.0)
        brightness_score = 0.60 * luminance + 0.25 * shadows + 0.15 * contrast
        quality = float(np.clip(0.55 * sharpness + 0.45 * brightness_score, 0.0, 1.0))
        return {
            "blur_score": float(np.clip(blur_score, 0.0, 1.0)),
            "brightness_score": float(np.clip(brightness_score, 0.0, 1.0)),
            "quality": quality,
            "blur_level": self._blur_level(blur_score),
            "low_light_level": self._low_light_level(brightness_score),
        }

    def _enhance(self, rgb: np.ndarray, protocol: ConditionProtocol, assessment: dict[str, object]) -> tuple[np.ndarray, tuple[str, ...], str | None]:
        output = rgb.copy()
        chain: list[str] = []
        use_low_light = protocol in {ConditionProtocol.LOW_LIGHT, ConditionProtocol.LOW_LIGHT_BLUR}
        use_blur = protocol in {ConditionProtocol.BLUR, ConditionProtocol.LOW_LIGHT_BLUR}
        if use_low_light and assessment["low_light_level"] is not LowLightLevel.NORMAL_LIGHT:
            lab = cv2.cvtColor(output, cv2.COLOR_RGB2LAB)
            light, a, b = cv2.split(lab)
            light = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(light)
            output = cv2.cvtColor(cv2.merge((light, a, b)), cv2.COLOR_LAB2RGB)
            chain.append("EXPOSURE_RECOVERY_CLAHE")
            output = cv2.bilateralFilter(output, 5, 25, 25)
            chain.append("MILD_DENOISE_BILATERAL")
        if use_blur and assessment["blur_level"] is not BlurLevel.CLEAR:
            base = cv2.GaussianBlur(output, (0, 0), 1.1)
            output = cv2.addWeighted(output, 1.65, base, -0.65, 0)
            chain.append("UNSHARP_MASK")
        return output, tuple(chain), ("CLASSICAL_" + "+".join(chain) if chain else None)

    @staticmethod
    def _normalize(value: float, low: float, high: float) -> float:
        return float(np.clip((value - low) / (high - low), 0.0, 1.0))

    def _blur_level(self, score: float) -> BlurLevel:
        if score >= self.config.blur_severe_score:
            return BlurLevel.SEVERE_BLUR
        if score >= self.config.blur_moderate_score:
            return BlurLevel.MODERATE_BLUR
        if score >= self.config.blur_mild_score:
            return BlurLevel.MILD_BLUR
        return BlurLevel.CLEAR

    def _low_light_level(self, score: float) -> LowLightLevel:
        if score <= self.config.low_light_severe_score:
            return LowLightLevel.SEVERE_LOW_LIGHT
        if score <= self.config.low_light_moderate_score:
            return LowLightLevel.MODERATE_LOW_LIGHT
        if score <= self.config.low_light_mild_score:
            return LowLightLevel.MILD_LOW_LIGHT
        return LowLightLevel.NORMAL_LIGHT

    def _reliability(self, quality: float) -> ReliabilityLevel:
        if quality < self.config.low_quality_score:
            return ReliabilityLevel.LOW
        if quality < self.config.medium_quality_score:
            return ReliabilityLevel.MEDIUM
        return ReliabilityLevel.HIGH

    @staticmethod
    def _visual_condition(assessment: dict[str, object]) -> VisualCondition:
        blurred = assessment["blur_level"] is not BlurLevel.CLEAR
        dark = assessment["low_light_level"] is not LowLightLevel.NORMAL_LIGHT
        if blurred and dark:
            return VisualCondition.LOW_LIGHT_BLUR
        if blurred:
            return VisualCondition.BLUR
        if dark:
            return VisualCondition.LOW_LIGHT
        return VisualCondition.NORMAL

    def _uncertainty_hints(self, assessment: dict[str, object]) -> tuple[str, ...]:
        hints: list[str] = []
        if assessment["blur_level"] is BlurLevel.SEVERE_BLUR:
            hints.append("BLUR_TOO_SEVERE")
        if assessment["low_light_level"] is LowLightLevel.SEVERE_LOW_LIGHT:
            hints.append("LOW_LIGHT_TOO_SEVERE")
        if float(assessment["quality"]) < self.config.low_quality_score:
            hints.extend(("LOW_IMAGE_QUALITY", "PERCEPTION_UNCERTAIN"))
        return tuple(hints)
