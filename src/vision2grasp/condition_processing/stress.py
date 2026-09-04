"""Deterministic visual-condition stress simulation for research experiments."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib

import cv2
import numpy as np

from vision2grasp.contracts import RGBFrame

from .contracts import (
    ConditionProtocol,
    ConditionStressReport,
    ConditionedFrame,
    StressBlurType,
    StressLevel,
    StressStrategy,
)
from .processor import ConditionProcessor


@dataclass(frozen=True, slots=True)
class StressProfile:
    brightness: float
    contrast: float
    noise_sigma: float
    gaussian_kernel: int
    gaussian_sigma: float
    motion_length: int
    motion_angle_deg: float


STRESS_PROFILES = {
    StressLevel.MILD: StressProfile(0.72, 0.86, 4.0, 5, 1.2, 5, 5.0),
    StressLevel.MODERATE: StressProfile(0.48, 0.68, 9.0, 11, 2.4, 11, 15.0),
    StressLevel.SEVERE: StressProfile(0.25, 0.46, 16.0, 21, 4.5, 21, 27.0),
}


@dataclass(frozen=True, slots=True)
class StressSimulationResult:
    raw_frame: RGBFrame
    degraded_frame: RGBFrame
    condition: ConditionProtocol
    strategy: StressStrategy
    level: StressLevel
    blur_type: StressBlurType
    random_seed: int
    degradation_chain: tuple[str, ...]
    parameters: dict[str, object]
    raw_sha256: str
    degraded_sha256: str


class ConditionStressSimulator:
    """Apply controlled image degradation without touching robot-side logic."""

    def simulate(
        self,
        frame: RGBFrame,
        condition: ConditionProtocol | str,
        *,
        strategy: StressStrategy | str = StressStrategy.STRESS_ONLY,
        level: StressLevel | str = StressLevel.MODERATE,
        blur_type: StressBlurType | str = StressBlurType.GAUSSIAN,
        random_seed: int = 7,
    ) -> StressSimulationResult:
        selected = self._enum(ConditionProtocol, condition)
        selected_strategy = self._enum(StressStrategy, strategy)
        selected_level = self._enum(StressLevel, level)
        selected_blur = self._enum(StressBlurType, blur_type)
        if random_seed < 0 or random_seed > 2**32 - 1:
            raise ValueError("随机种子必须位于 [0, 2^32 - 1] Random seed out of range")
        if selected is ConditionProtocol.OCCLUSION:
            raise ValueError("遮挡压力模拟尚未实现 Occlusion stress simulation pending")
        raw_rgb = np.ascontiguousarray(frame.rgb.copy(), dtype=np.uint8)
        output = raw_rgb.copy()
        chain: list[str] = []
        profile = STRESS_PROFILES[selected_level]

        if selected in {ConditionProtocol.LOW_LIGHT, ConditionProtocol.LOW_LIGHT_BLUR}:
            output = self._low_light(output, profile, random_seed + frame.frame_id)
            chain.extend(("BRIGHTNESS_REDUCTION", "CONTRAST_REDUCTION", "SHADOW_NOISE"))
        if selected in {ConditionProtocol.BLUR, ConditionProtocol.LOW_LIGHT_BLUR}:
            if selected_blur is StressBlurType.GAUSSIAN:
                output = cv2.GaussianBlur(
                    output,
                    (profile.gaussian_kernel, profile.gaussian_kernel),
                    profile.gaussian_sigma,
                )
                chain.append("GAUSSIAN_BLUR")
            else:
                output = cv2.filter2D(output, -1, self._motion_kernel(profile))
                chain.append("MOTION_BLUR")

        raw_hash = hashlib.sha256(raw_rgb.tobytes()).hexdigest()
        degraded_hash = hashlib.sha256(output.tobytes()).hexdigest()
        degraded_id = frame.frame_id
        if selected is not ConditionProtocol.NORMAL:
            degraded_id = self._frame_id(
                frame,
                f"stress|{selected.value}|{selected_level.value}|{selected_blur.value}|{random_seed}|{degraded_hash}",
            )
        parameters = {
            "profile_version": "gongshu.stress-profile/v1",
            "brightness": profile.brightness if "BRIGHTNESS_REDUCTION" in chain else 1.0,
            "contrast": profile.contrast if "CONTRAST_REDUCTION" in chain else 1.0,
            "noise_sigma": profile.noise_sigma if "SHADOW_NOISE" in chain else 0.0,
            "gaussian_kernel": profile.gaussian_kernel if selected_blur is StressBlurType.GAUSSIAN and "GAUSSIAN_BLUR" in chain else None,
            "gaussian_sigma": profile.gaussian_sigma if "GAUSSIAN_BLUR" in chain else None,
            "motion_length": profile.motion_length if "MOTION_BLUR" in chain else None,
            "motion_angle_deg": profile.motion_angle_deg if "MOTION_BLUR" in chain else None,
        }
        return StressSimulationResult(
            raw_frame=self._frame(frame, frame.frame_id, raw_rgb),
            degraded_frame=self._frame(frame, degraded_id, output),
            condition=selected,
            strategy=selected_strategy,
            level=selected_level,
            blur_type=selected_blur,
            random_seed=random_seed,
            degradation_chain=tuple(chain),
            parameters=parameters,
            raw_sha256=raw_hash,
            degraded_sha256=degraded_hash,
        )

    @staticmethod
    def _low_light(rgb: np.ndarray, profile: StressProfile, seed: int) -> np.ndarray:
        value = rgb.astype(np.float32) * profile.brightness
        mean = np.mean(value, axis=(0, 1), keepdims=True)
        value = (value - mean) * profile.contrast + mean
        luminance = cv2.cvtColor(np.clip(value, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
        shadow_weight = np.power(1.0 - luminance.astype(np.float32) / 255.0, 1.5)[..., None]
        noise = np.random.default_rng(seed).normal(0.0, profile.noise_sigma, value.shape)
        return np.clip(value + noise * shadow_weight, 0, 255).astype(np.uint8)

    @staticmethod
    def _motion_kernel(profile: StressProfile) -> np.ndarray:
        length = profile.motion_length
        kernel = np.zeros((length, length), dtype=np.float32)
        kernel[length // 2, :] = 1.0
        rotation = cv2.getRotationMatrix2D(
            ((length - 1) / 2.0, (length - 1) / 2.0), profile.motion_angle_deg, 1.0
        )
        kernel = cv2.warpAffine(kernel, rotation, (length, length))
        total = float(np.sum(kernel))
        return kernel / total if total > 0.0 else kernel

    @staticmethod
    def _frame(source: RGBFrame, frame_id: int, rgb: np.ndarray) -> RGBFrame:
        return RGBFrame(frame_id, source.timestamp_s, source.camera_name, rgb)

    @staticmethod
    def _frame_id(frame: RGBFrame, payload: str) -> int:
        seed = f"{frame.frame_id}|{frame.timestamp_s!r}|{payload}".encode()
        value = int.from_bytes(hashlib.sha256(seed).digest()[:6], "big")
        return (value + 1) % (2**48) if value == frame.frame_id else value

    @staticmethod
    def _enum(enum_type, value):
        return value if isinstance(value, enum_type) else enum_type(str(value).upper().replace("-", "_"))


class ConditionExperimentProcessor:
    """Compose stress simulation with the unchanged v0.8 assessment/recovery layer."""

    def __init__(
        self,
        condition_processor: ConditionProcessor,
        stress_simulator: ConditionStressSimulator | None = None,
    ) -> None:
        self.condition_processor = condition_processor
        self.stress_simulator = stress_simulator or ConditionStressSimulator()

    def process(
        self,
        frame: RGBFrame,
        condition: ConditionProtocol | str,
        *,
        strategy: StressStrategy | str = StressStrategy.STRESS_ONLY,
        level: StressLevel | str = StressLevel.MODERATE,
        blur_type: StressBlurType | str = StressBlurType.GAUSSIAN,
        random_seed: int = 7,
        research_mode: bool = True,
    ) -> ConditionedFrame:
        selected = ConditionStressSimulator._enum(ConditionProtocol, condition)
        if not research_mode:
            selected = ConditionProtocol.NORMAL
        stress = self.stress_simulator.simulate(
            frame,
            selected,
            strategy=strategy,
            level=level,
            blur_type=blur_type,
            random_seed=random_seed,
        )
        recovery = stress.strategy is StressStrategy.STRESS_PLUS_RECOVERY and selected is not ConditionProtocol.NORMAL
        conditioned = self.condition_processor.process(
            stress.degraded_frame,
            selected if recovery else ConditionProtocol.NORMAL,
        )
        report = conditioned.report
        if not recovery and selected is not ConditionProtocol.NORMAL:
            report = replace(report, protocol=selected)
        enhanced = conditioned.processed_frame if report.enhancement_applied else None
        stress_report = ConditionStressReport(
            condition=selected,
            strategy=stress.strategy,
            level=stress.level,
            blur_type=stress.blur_type,
            random_seed=stress.random_seed,
            raw_frame_id=stress.raw_frame.frame_id,
            degraded_frame_id=stress.degraded_frame.frame_id,
            enhanced_frame_id=None if enhanced is None else enhanced.frame_id,
            pipeline_frame_id=conditioned.processed_frame.frame_id,
            raw_sha256=stress.raw_sha256,
            degraded_sha256=stress.degraded_sha256,
            enhanced_sha256=None if enhanced is None else report.processed_sha256,
            pipeline_sha256=report.processed_sha256,
            degradation_chain=stress.degradation_chain,
            parameters=stress.parameters,
        )
        report = replace(report, stress_test=stress_report)
        return ConditionedFrame(
            raw_frame=conditioned.raw_frame,
            processed_frame=conditioned.processed_frame,
            report=report,
            source_frame=stress.raw_frame,
            degraded_frame=stress.degraded_frame,
            enhanced_frame=enhanced,
        )
