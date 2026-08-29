"""CPU geometry planner for camera-frame target point clouds."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vision2grasp.spatial_perception import DepthMode, SpatialObservation

from .contracts import (
    GraspCandidate,
    GraspConfidence,
    GraspPlan,
    PlanningState,
)


class GraspPlanningError(ValueError):
    code = "GRASP_PLANNING_FAILED"


class EmptyPointCloudError(GraspPlanningError):
    code = "POINT_CLOUD_EMPTY"


class AbnormalScaleError(GraspPlanningError):
    code = "ABNORMAL_SCALE"


class GripperWidthError(GraspPlanningError):
    code = "WIDTH_LIMIT"


@dataclass(frozen=True, slots=True)
class GeometricGraspPlannerConfig:
    minimum_points: int = 30
    extent_lower_quantile: float = 0.02
    extent_upper_quantile: float = 0.98
    minimum_gripper_width_m: float = 0.01
    maximum_gripper_width_m: float = 0.08
    width_clearance_m: float = 0.008
    maximum_object_extent_m: float = 0.35
    point_support_reference: int = 1000


class GeometricGraspPlanner:
    """Generate and rank top-down PCA candidates without simulation truth."""

    coordinate_frame = "OPENCV_CAMERA_X_RIGHT_Y_DOWN_Z_FORWARD"
    source = "GEOMETRIC_PCA_TOP_DOWN"

    def __init__(self, config: GeometricGraspPlannerConfig | None = None) -> None:
        self.config = config or GeometricGraspPlannerConfig()

    def plan(self, observation: SpatialObservation) -> tuple[GraspPlan, tuple[GraspCandidate, ...]]:
        points = np.asarray(observation.target_point_cloud, dtype=np.float64)
        if points.ndim != 2 or points.shape[1:] != (3,) or points.shape[0] == 0:
            raise EmptyPointCloudError("target point cloud is empty")
        if points.shape[0] < self.config.minimum_points:
            raise EmptyPointCloudError(
                f"point count below minimum: {points.shape[0]} < {self.config.minimum_points}"
            )
        if not np.all(np.isfinite(points)):
            raise GraspPlanningError("point cloud contains non-finite values")
        if observation.depth_mode is DepthMode.RELATIVE:
            raise GraspPlanningError("relative depth cannot satisfy metric gripper limits")

        planar = points[:, :2]
        center_xy = np.median(planar, axis=0)
        centered = planar - center_xy
        covariance = centered.T @ centered / points.shape[0]
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        order = np.argsort(eigenvalues)[::-1]
        major_variance = float(eigenvalues[order[0]])
        minor_variance = max(float(eigenvalues[order[1]]), 0.0)
        if major_variance <= np.finfo(np.float64).eps:
            raise GraspPlanningError("target planar variance is too small")

        major = np.asarray(eigenvectors[:, order[0]], dtype=np.float64)
        dominant = int(np.argmax(np.abs(major)))
        if major[dominant] < 0.0:
            major = -major
        major /= np.linalg.norm(major)
        closing = np.array([-major[1], major[0]], dtype=np.float64)

        major_span = self._robust_span(centered @ major)
        minor_span = self._robust_span(centered @ closing)
        depth_span = self._robust_span(points[:, 2])
        extents = np.array([minor_span, major_span, depth_span], dtype=np.float64)
        if np.any(extents <= 1e-5) or float(np.max(extents)) > self.config.maximum_object_extent_m:
            raise AbnormalScaleError(f"abnormal target extent: {extents.tolist()}")

        required_width = minor_span + self.config.width_clearance_m
        if not self.config.minimum_gripper_width_m <= required_width <= self.config.maximum_gripper_width_m:
            raise GripperWidthError(
                f"required gripper width {required_width:.4f} m is outside "
                f"[{self.config.minimum_gripper_width_m:.4f}, "
                f"{self.config.maximum_gripper_width_m:.4f}] m"
            )

        factors = self._confidence_factors(
            observation=observation,
            point_count=points.shape[0],
            major_variance=major_variance,
            minor_variance=minor_variance,
            required_width=required_width,
        )
        candidates = self._generate_candidates(
            observation=observation,
            center_xy=center_xy,
            major=major,
            closing=closing,
            major_span=major_span,
            required_width=required_width,
            factors=factors,
        )
        best = max(candidates, key=lambda candidate: candidate.quality_score)
        uncertainty: list[str] = []
        if observation.depth_mode is DepthMode.APPROX_METRIC:
            uncertainty.append("APPROX_METRIC_INPUT")
        if observation.camera_intrinsics.calibration_state.value == "UNCALIBRATED":
            uncertainty.append("UNCALIBRATED_INTRINSICS")
        confidence_value = float(
            0.25 * factors["point_support"]
            + 0.30 * factors["depth_validity"]
            + 0.25 * factors["pca_stability"]
            + 0.20 * factors["width_margin"]
        )
        plan = GraspPlan(
            target_id=observation.target_instance_id,
            snapshot_id=observation.snapshot_id,
            source_frame_id=observation.source_frame_id,
            grasp_point_xyz=best.grasp_point_xyz,
            approach_vector=best.approach_vector,
            closing_vector=best.closing_vector,
            grasp_angle=best.grasp_angle,
            gripper_width=best.gripper_width,
            quality_score=best.quality_score,
            confidence=GraspConfidence(value=confidence_value, factors=factors),
            source=self.source,
            coordinate_frame=self.coordinate_frame,
            depth_mode=observation.depth_mode,
            planning_state=PlanningState.READY,
            intrinsics_source=observation.camera_intrinsics.source,
            calibration_state=observation.camera_intrinsics.calibration_state,
            uncertainty=tuple(uncertainty),
            object_extents_xyz=extents,
            candidate_count=len(candidates),
        )
        return plan, candidates

    def _generate_candidates(
        self,
        *,
        observation: SpatialObservation,
        center_xy: np.ndarray,
        major: np.ndarray,
        closing: np.ndarray,
        major_span: float,
        required_width: float,
        factors: dict[str, float],
    ) -> tuple[GraspCandidate, ...]:
        near_surface_z = float(
            np.quantile(observation.target_point_cloud[:, 2], self.config.extent_lower_quantile)
        )
        approach = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        closing_3d = np.array([closing[0], closing[1], 0.0], dtype=np.float64)
        angle = float(np.arctan2(closing[1], closing[0]))
        candidates: list[GraspCandidate] = []
        for index, offset_scale in enumerate((0.0, -0.15, 0.15)):
            offset = major * major_span * offset_scale
            centrality = 1.0 - abs(offset_scale) / 0.3
            quality = float(
                0.25 * factors["point_support"]
                + 0.30 * factors["depth_validity"]
                + 0.20 * factors["pca_stability"]
                + 0.20 * factors["width_margin"]
                + 0.05 * centrality
            )
            candidates.append(
                GraspCandidate(
                    candidate_id=f"pca-top-{index}",
                    grasp_point_xyz=np.array(
                        [center_xy[0] + offset[0], center_xy[1] + offset[1], near_surface_z],
                        dtype=np.float64,
                    ),
                    approach_vector=approach,
                    closing_vector=closing_3d,
                    grasp_angle=angle,
                    gripper_width=required_width,
                    quality_score=float(np.clip(quality, 0.0, 1.0)),
                    score_factors={**factors, "centrality": float(centrality)},
                )
            )
        return tuple(candidates)

    def _confidence_factors(
        self,
        *,
        observation: SpatialObservation,
        point_count: int,
        major_variance: float,
        minor_variance: float,
        required_width: float,
    ) -> dict[str, float]:
        gripper_span = self.config.maximum_gripper_width_m - self.config.minimum_gripper_width_m
        lower_margin = (required_width - self.config.minimum_gripper_width_m) / gripper_span
        upper_margin = (self.config.maximum_gripper_width_m - required_width) / gripper_span
        return {
            "point_support": float(np.clip(point_count / self.config.point_support_reference, 0.0, 1.0)),
            "depth_validity": float(
                np.clip(
                    observation.target_depth.valid_ratio * observation.target_depth.inlier_ratio,
                    0.0,
                    1.0,
                )
            ),
            "pca_stability": float(np.clip(1.0 - minor_variance / major_variance, 0.0, 1.0)),
            "width_margin": float(np.clip(2.0 * min(lower_margin, upper_margin), 0.0, 1.0)),
        }

    def _robust_span(self, values: np.ndarray) -> float:
        lower, upper = np.quantile(
            values,
            [self.config.extent_lower_quantile, self.config.extent_upper_quantile],
        )
        return float(max(upper - lower, 0.0))

