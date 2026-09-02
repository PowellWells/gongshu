"""Target-aware Top-K extraction, feasibility filtering, and ranking."""

from __future__ import annotations

from dataclasses import dataclass
import time

import cv2
import numpy as np

from vision2grasp.spatial_perception import DepthMode, GeometrySanityStatus, SpatialObservation
from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import (
    CandidateFeasibility,
    CollisionState,
    GraspCandidate,
    GraspConfidence,
    GraspMaps,
    GraspPlan,
    GraspPlanningOutcome,
    GraspStage,
    PlanningMode,
    PlanningState,
    ReachabilityState,
)
from .detector import GRCONVNET_MODEL_ASSET, GraspProgressCallback


@dataclass(frozen=True, slots=True)
class TopKGraspPlannerConfig:
    top_k: int = 8
    minimum_quality: float = 0.20
    minimum_points: int = 30
    minimum_gripper_width_m: float = 0.01
    maximum_gripper_width_m: float = 0.08
    maximum_object_extent_m: float = 0.35
    minimum_valid_depth_ratio: float = 0.50
    minimum_geometry_confidence: float = 0.35
    minimum_mask_margin_ratio: float = 0.025
    point_support_reference: int = 1000
    extent_lower_quantile: float = 0.02
    extent_upper_quantile: float = 0.98

    def __post_init__(self) -> None:
        if not 5 <= self.top_k <= 10:
            raise ValueError("top_k must be in [5, 10]")
        if not 0.0 <= self.minimum_quality <= 1.0:
            raise ValueError("minimum_quality must be in [0, 1]")
        if not 0.0 < self.minimum_gripper_width_m < self.maximum_gripper_width_m:
            raise ValueError("gripper width limits must be positive and ordered")
        if self.minimum_points <= 0 or self.point_support_reference < self.minimum_points:
            raise ValueError("point support limits are invalid")
        if not 0.0 <= self.minimum_valid_depth_ratio <= 1.0:
            raise ValueError("minimum_valid_depth_ratio must be in [0, 1]")
        if not 0.0 <= self.minimum_geometry_confidence <= 1.0:
            raise ValueError("minimum_geometry_confidence must be in [0, 1]")


class PixelWiseTopKGraspPlanner:
    coordinate_frame = "OPENCV_CAMERA_X_RIGHT_Y_DOWN_Z_FORWARD"
    source = "PIXEL_WISE_ANTIPODAL_RGBD"

    def __init__(self, detector, config: TopKGraspPlannerConfig | None = None) -> None:
        self.detector = detector
        self.config = config or TopKGraspPlannerConfig()

    def plan(
        self,
        observation: SpatialObservation,
        snapshot: TargetSceneSnapshot,
        *,
        mode: PlanningMode = PlanningMode.RESEARCH,
        progress: GraspProgressCallback | None = None,
    ) -> GraspPlanningOutcome:
        started = time.perf_counter()
        maps = self.detector.infer(snapshot, observation, progress)
        self._emit(progress, GraspStage.CANDIDATE_EXTRACTION)
        peaks = self._top_k_peaks(maps, snapshot.target.mask, snapshot.target.bbox_xyxy)
        self._emit(progress, GraspStage.FEASIBILITY_FILTERING)
        confidence = self._geometry_confidence(observation)
        extents = self._object_extents(observation)
        candidates = tuple(
            self._candidate(
                index=index,
                row=row,
                column=column,
                maps=maps,
                observation=observation,
                snapshot=snapshot,
                confidence=confidence,
                extents=extents,
            )
            for index, (row, column) in enumerate(peaks, start=1)
        )
        self._emit(progress, GraspStage.CANDIDATE_RANKING)
        candidates = tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    candidate.executable,
                    candidate.ranking_score,
                    candidate.quality_score,
                    candidate.candidate_id,
                ),
                reverse=True,
            )
        )
        executable = [candidate for candidate in candidates if candidate.executable]
        elapsed = time.perf_counter() - started
        if not executable:
            return GraspPlanningOutcome(
                candidates=candidates,
                maps=maps,
                object_extents_xyz=extents,
                plan=None,
                rejection_reason=self._final_rejection_reason(candidates),
                planning_time_s=elapsed,
            )
        best = executable[0]
        uncertainty: list[str] = ["ROBOT_FRAME_TRANSFORM_UNAVAILABLE"]
        if observation.depth_mode is DepthMode.APPROX_METRIC:
            uncertainty.append("APPROX_METRIC_INPUT")
        if observation.camera_intrinsics.calibration_state.value == "UNCALIBRATED":
            uncertainty.append("UNCALIBRATED_INTRINSICS")
        plan = GraspPlan(
            target_id=observation.target_instance_id,
            snapshot_id=observation.snapshot_id,
            source_frame_id=observation.source_frame_id,
            spatial_observation_id=observation.geometry_chain_id,
            grasp_point_xyz=best.grasp_point_xyz,
            approach_vector=best.approach_vector,
            closing_vector=best.closing_vector,
            grasp_angle=best.grasp_angle,
            gripper_width=best.gripper_width,
            quality_score=best.quality_score,
            confidence=confidence,
            source=self.source,
            coordinate_frame=self.coordinate_frame,
            depth_mode=observation.depth_mode,
            planning_state=PlanningState.GRASP_READY,
            intrinsics_source=observation.camera_intrinsics.source,
            calibration_state=observation.camera_intrinsics.calibration_state,
            uncertainty=tuple(uncertainty),
            object_extents_xyz=extents,
            candidate_count=len(candidates),
            candidates=candidates,
            best_candidate_id=best.candidate_id,
            planning_time_s=elapsed,
            mode=mode,
            model_metadata={
                "baseline": "GR-ConvNet",
                "model_revision": GRCONVNET_MODEL_ASSET.revision,
                "model_sha256": GRCONVNET_MODEL_ASSET.sha256,
                "license": GRCONVNET_MODEL_ASSET.license,
                "compute_device": maps.compute_device,
                "model_location": maps.model_location,
                "model_was_ready": maps.model_was_ready,
                "model_load_s": maps.model_load_time_s,
                "inference_s": maps.inference_time_s,
                "input_size": list(maps.model_input_size),
            },
        )
        return GraspPlanningOutcome(candidates, maps, extents, plan, None, elapsed)

    def _top_k_peaks(
        self,
        maps: GraspMaps,
        target_mask: np.ndarray,
        bbox: tuple[float, float, float, float],
    ) -> tuple[tuple[int, int], ...]:
        mask = np.asarray(target_mask, dtype=bool)
        rows, columns = np.nonzero(mask)
        if rows.size == 0:
            return ()
        values = maps.quality[rows, columns]
        order = np.argsort(values, kind="stable")[::-1]
        x1, y1, x2, y2 = bbox
        minimum_distance = max(3.0, min(x2 - x1, y2 - y1) * 0.08)
        accepted: list[tuple[int, int]] = []
        for candidate_index in order:
            row = int(rows[candidate_index])
            column = int(columns[candidate_index])
            if all(
                (row - other_row) ** 2 + (column - other_column) ** 2
                >= minimum_distance**2
                for other_row, other_column in accepted
            ):
                accepted.append((row, column))
                if len(accepted) == self.config.top_k:
                    break
        return tuple(accepted)

    def _candidate(
        self,
        *,
        index: int,
        row: int,
        column: int,
        maps: GraspMaps,
        observation: SpatialObservation,
        snapshot: TargetSceneSnapshot,
        confidence: GraspConfidence,
        extents: np.ndarray,
    ) -> GraspCandidate:
        quality = float(np.clip(maps.quality[row, column], 0.0, 1.0))
        angle = float(maps.angle[row, column])
        width_px = float(max(maps.width_px[row, column], 1e-6))
        mask = np.asarray(snapshot.target.mask, dtype=np.uint8)
        distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        margin = float(distance[row, column])
        x1, y1, x2, y2 = snapshot.target.bbox_xyxy
        margin_reference = max(min(x2 - x1, y2 - y1) * 0.25, 1.0)
        margin_factor = float(np.clip(margin / margin_reference, 0.0, 1.0))
        local_depth_ratio, depth = self._local_depth(observation, snapshot, row, column, width_px)
        intrinsics = observation.camera_intrinsics.intrinsics
        meters_per_pixel = depth * np.sqrt(
            (np.cos(angle) / intrinsics.fx) ** 2 + (np.sin(angle) / intrinsics.fy) ** 2
        )
        width_m = float(max(width_px * meters_per_pixel, np.finfo(np.float32).eps))
        center_xyz = np.array(
            [
                (column - intrinsics.cx) * depth / intrinsics.fx,
                (row - intrinsics.cy) * depth / intrinsics.fy,
                depth,
            ],
            dtype=np.float64,
        )
        closing = np.array([np.cos(angle), np.sin(angle), 0.0], dtype=np.float64)
        reasons: list[str] = []
        if quality < self.config.minimum_quality:
            reasons.append("LOW_GRASP_QUALITY")
        if not snapshot.target.mask[row, column]:
            reasons.append("TARGET_MISMATCH")
        required_margin = max(min(x2 - x1, y2 - y1) * self.config.minimum_mask_margin_ratio, 1.0)
        if margin < required_margin:
            reasons.append("TARGET_EDGE")
        if local_depth_ratio < self.config.minimum_valid_depth_ratio:
            reasons.append("INVALID_DEPTH")
        if observation.depth_mode is DepthMode.RELATIVE:
            reasons.append("INVALID_DEPTH_SCALE")
        if float(np.max(extents)) > self.config.maximum_object_extent_m:
            reasons.append("ABNORMAL_SCALE")
        if width_m < self.config.minimum_gripper_width_m:
            reasons.append("GRIPPER_TOO_NARROW")
        elif width_m > self.config.maximum_gripper_width_m:
            reasons.append("GRIPPER_TOO_WIDE")
        if confidence.value < self.config.minimum_geometry_confidence:
            reasons.append("LOW_GEOMETRY_CONFIDENCE")
        if observation.target_point_cloud.shape[0] < self.config.minimum_points:
            reasons.append("INSUFFICIENT_GEOMETRY")
        width_factor = self._width_compatibility(width_m)
        score_factors = {
            "grasp_quality": quality,
            "width_compatibility": width_factor,
            "target_mask_margin": margin_factor,
            "valid_depth_ratio": local_depth_ratio,
            "geometry_confidence": confidence.value,
            "workspace_reachability": 0.5,
        }
        ranking = float(
            np.clip(
                0.55 * quality
                + 0.15 * width_factor
                + 0.12 * margin_factor
                + 0.08 * local_depth_ratio
                + 0.10 * confidence.value,
                0.0,
                1.0,
            )
        )
        return GraspCandidate(
            candidate_id=f"candidate-{index:02d}",
            center_uv=(float(column), float(row)),
            grasp_point_xyz=center_xyz,
            approach_vector=np.array([0.0, 0.0, 1.0], dtype=np.float64),
            closing_vector=closing,
            grasp_angle=angle,
            width_px=width_px,
            gripper_width=width_m,
            quality_score=quality,
            ranking_score=ranking,
            score_factors=score_factors,
            feasibility=(
                CandidateFeasibility.REJECTED if reasons else CandidateFeasibility.EXECUTABLE
            ),
            rejection_reasons=tuple(reasons),
            source_frame_id=observation.source_frame_id,
            target_instance_id=observation.target_instance_id,
            target_mask_margin_px=margin,
            valid_depth_ratio=local_depth_ratio,
            width_compatibility=width_factor,
            reachability=ReachabilityState.UNKNOWN,
            collision_feasibility=CollisionState.UNKNOWN,
            geometry_confidence=confidence.value,
        )

    @staticmethod
    def _local_depth(
        observation: SpatialObservation,
        snapshot: TargetSceneSnapshot,
        row: int,
        column: int,
        width_px: float,
    ) -> tuple[float, float]:
        depth = np.asarray(observation.depth_frame.values, dtype=np.float32)
        radius = int(np.clip(width_px / 8.0, 2.0, 12.0))
        y1 = max(row - radius, 0)
        y2 = min(row + radius + 1, depth.shape[0])
        x1 = max(column - radius, 0)
        x2 = min(column + radius + 1, depth.shape[1])
        local_mask = snapshot.target.mask[y1:y2, x1:x2]
        local_depth = depth[y1:y2, x1:x2]
        valid = local_mask & np.isfinite(local_depth) & (local_depth > 0.0)
        denominator = max(int(np.count_nonzero(local_mask)), 1)
        ratio = float(np.count_nonzero(valid) / denominator)
        if np.any(valid):
            return ratio, float(np.median(local_depth[valid]))
        return ratio, float(observation.target_depth.value)

    def _width_compatibility(self, width_m: float) -> float:
        lower = self.config.minimum_gripper_width_m
        upper = self.config.maximum_gripper_width_m
        if not lower <= width_m <= upper:
            return 0.0
        center = (lower + upper) * 0.5
        half = (upper - lower) * 0.5
        return float(np.clip(1.0 - abs(width_m - center) / half, 0.0, 1.0))

    def _geometry_confidence(self, observation: SpatialObservation) -> GraspConfidence:
        diagnostics = observation.geometry_diagnostics
        mask_integrity = (
            1.0 if diagnostics is None else diagnostics.target_mask_largest_component_ratio
        )
        factors = {
            "point_support": float(
                np.clip(
                    observation.target_point_cloud.shape[0] / self.config.point_support_reference,
                    0.0,
                    1.0,
                )
            ),
            "depth_validity": float(
                np.clip(
                    observation.target_depth.valid_ratio * observation.target_depth.inlier_ratio,
                    0.0,
                    1.0,
                )
            ),
            "geometry_sanity": (
                1.0
                if observation.geometry_sanity.status is GeometrySanityStatus.PASS
                else 0.0
            ),
            "mask_integrity": float(np.clip(mask_integrity, 0.0, 1.0)),
        }
        value = float(
            0.25 * factors["point_support"]
            + 0.35 * factors["depth_validity"]
            + 0.25 * factors["geometry_sanity"]
            + 0.15 * factors["mask_integrity"]
        )
        return GraspConfidence(value=value, factors=factors)

    def _object_extents(self, observation: SpatialObservation) -> np.ndarray:
        points = np.asarray(observation.target_point_cloud, dtype=np.float64)
        if points.shape[0] < self.config.minimum_points:
            return np.full(3, np.finfo(np.float32).eps, dtype=np.float64)
        bounds = np.quantile(
            points,
            [self.config.extent_lower_quantile, self.config.extent_upper_quantile],
            axis=0,
        )
        return np.maximum(bounds[1] - bounds[0], np.finfo(np.float32).eps)

    @staticmethod
    def _final_rejection_reason(candidates: tuple[GraspCandidate, ...]) -> str:
        if not candidates:
            return "NO_VALID_CANDIDATE"
        all_low_quality = all(
            "LOW_GRASP_QUALITY" in candidate.rejection_reasons for candidate in candidates
        )
        width_reason = next(
            (
                reason
                for reason in ("GRIPPER_TOO_NARROW", "GRIPPER_TOO_WIDE")
                if all(reason in candidate.rejection_reasons for candidate in candidates)
            ),
            None,
        )
        if all_low_quality and width_reason is not None:
            return f"LOW_GRASP_QUALITY+{width_reason}"
        if width_reason is not None:
            return width_reason
        reasons = [reason for candidate in candidates for reason in candidate.rejection_reasons]
        priorities = (
            "ABNORMAL_SCALE",
            "OUT_OF_REACH",
            "INSUFFICIENT_GEOMETRY",
            "LOW_GEOMETRY_CONFIDENCE",
            "INVALID_DEPTH",
            "TARGET_MISMATCH",
            "LOW_GRASP_QUALITY",
            "TARGET_EDGE",
        )
        selected = next((reason for reason in priorities if reason in reasons), "NO_VALID_CANDIDATE")
        return selected

    @staticmethod
    def _emit(progress: GraspProgressCallback | None, stage: GraspStage) -> None:
        if progress is not None:
            progress(stage, None)
