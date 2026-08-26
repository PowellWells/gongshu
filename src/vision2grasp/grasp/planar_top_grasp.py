"""Explainable two-dimensional top-grasp candidates for real RGB scenes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vision2grasp.contracts import PlanarGraspCandidate, PlanarLocalizedTarget


@dataclass(frozen=True, slots=True)
class PlanarTopGraspConfig:
    candidate_count: int = 3
    minimum_gripper_width_m: float = 0.01
    maximum_gripper_width_m: float = 0.08
    width_clearance_m: float = 0.008
    extent_lower_quantile: float = 0.02
    extent_upper_quantile: float = 0.98

    def __post_init__(self) -> None:
        if self.candidate_count < 2 or self.candidate_count > 6:
            raise ValueError("candidate_count must be between 2 and 6")
        if not 0.0 < self.minimum_gripper_width_m < self.maximum_gripper_width_m:
            raise ValueError("gripper width limits must be positive and ordered")
        if not 0.0 <= self.width_clearance_m < self.maximum_gripper_width_m:
            raise ValueError("width_clearance_m is outside the supported range")
        if not 0.0 <= self.extent_lower_quantile < 0.5:
            raise ValueError("extent_lower_quantile must be in [0, 0.5)")
        if not 0.5 < self.extent_upper_quantile <= 1.0:
            raise ValueError("extent_upper_quantile must be in (0.5, 1]")


class PlanarTopGraspPlanner:
    """Generate deterministic yaw variants around a calibrated table center."""

    def __init__(self, config: PlanarTopGraspConfig | None = None) -> None:
        self._config = config or PlanarTopGraspConfig()

    def plan(self, target: PlanarLocalizedTarget) -> tuple[PlanarGraspCandidate, ...]:
        points = np.asarray(target.points_table_m, dtype=np.float64)
        centered = points - target.center_table_m
        primary_closing_yaw = target.principal_yaw_rad + np.pi / 2.0
        candidates: list[PlanarGraspCandidate] = []
        for index in range(self._config.candidate_count):
            yaw = _canonical_gripper_yaw(
                primary_closing_yaw + index * np.pi / self._config.candidate_count
            )
            closing_axis = np.array([np.cos(yaw), np.sin(yaw)], dtype=np.float64)
            projection = centered @ closing_axis
            lower, upper = np.quantile(
                projection,
                [self._config.extent_lower_quantile, self._config.extent_upper_quantile],
            )
            estimated_width = max(float(upper - lower), 0.001)
            required_width = estimated_width + self._config.width_clearance_m
            feasible = (
                self._config.minimum_gripper_width_m
                <= required_width
                <= self._config.maximum_gripper_width_m
            )
            width_range = (
                self._config.maximum_gripper_width_m
                - self._config.minimum_gripper_width_m
            )
            width_margin = float(
                np.clip(
                    (self._config.maximum_gripper_width_m - required_width)
                    / width_range,
                    0.0,
                    1.0,
                )
            )
            orientation_alignment = float(
                1.0 - index / max(1, self._config.candidate_count - 1) * 0.12
            )
            compactness = float(np.clip(target.circularity, 0.0, 1.0))
            geometry_score = float(
                np.clip(
                    0.45 * width_margin
                    + 0.35 * orientation_alignment
                    + 0.20 * compactness,
                    0.0,
                    1.0,
                )
            )
            vision_score = float(target.detection.confidence)
            final_score = (
                float(np.clip(0.55 * vision_score + 0.45 * geometry_score, 0.0, 1.0))
                if feasible
                else 0.0
            )
            candidates.append(
                PlanarGraspCandidate(
                    candidate_id=f"real-top-{target.detection.class_name}-{index + 1}",
                    center_table_m=target.center_table_m.copy(),
                    yaw_rad=yaw,
                    estimated_gripper_width_m=required_width,
                    vision_score=vision_score,
                    geometry_score=geometry_score,
                    final_score=final_score,
                    width_feasible=feasible,
                    score_terms={
                        "vision_confidence": vision_score,
                        "geometry_score": geometry_score,
                        "width_margin": width_margin,
                        "orientation_alignment": orientation_alignment,
                        "mask_circularity": compactness,
                        "estimated_object_span_m": estimated_width,
                        "width_clearance_m": self._config.width_clearance_m,
                    },
                )
            )
        return tuple(
            sorted(candidates, key=lambda item: (-item.final_score, item.candidate_id))
        )


def _canonical_gripper_yaw(value: float) -> float:
    return float((value + np.pi / 2.0) % np.pi - np.pi / 2.0)


__all__ = ["PlanarTopGraspConfig", "PlanarTopGraspPlanner"]
