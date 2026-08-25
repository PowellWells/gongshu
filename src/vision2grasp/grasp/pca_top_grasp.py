"""Deterministic PCA-based top-grasp planning for localized point clouds."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import GraspCandidate, LocalizedTarget


@dataclass(frozen=True, slots=True)
class PCATopGraspConfig:
    """Geometry limits and scoring parameters for the Panda top grasp."""

    minimum_points: int = 30
    pca_inlier_quantile: float = 0.98
    extent_lower_quantile: float = 0.02
    extent_upper_quantile: float = 0.98
    circularity_ratio_threshold: float = 0.85
    minimum_planar_variance_m2: float = 1e-8
    minimum_gripper_width_m: float = 0.01
    maximum_gripper_width_m: float = 0.08
    width_clearance_m: float = 0.008
    point_support_reference: int = 1000
    upright_axisymmetric_class_names: tuple[str, ...] = ("bottle", "cup")
    upright_height_to_width_ratio: float = 1.5
    upright_grasp_height_quantile: float = 0.75

    def __post_init__(self) -> None:
        if self.minimum_points < 3:
            raise ValueError("minimum_points must be at least 3")
        if not 0.5 < self.pca_inlier_quantile <= 1.0:
            raise ValueError("pca_inlier_quantile must be in (0.5, 1]")
        if not 0.0 <= self.extent_lower_quantile < 0.5:
            raise ValueError("extent_lower_quantile must be in [0, 0.5)")
        if not 0.5 < self.extent_upper_quantile <= 1.0:
            raise ValueError("extent_upper_quantile must be in (0.5, 1]")
        if self.extent_lower_quantile >= self.extent_upper_quantile:
            raise ValueError("extent quantiles must be ordered")
        if not 0.0 <= self.circularity_ratio_threshold <= 1.0:
            raise ValueError("circularity_ratio_threshold must be in [0, 1]")
        if self.minimum_planar_variance_m2 <= 0.0:
            raise ValueError("minimum_planar_variance_m2 must be positive")
        if self.minimum_gripper_width_m <= 0.0:
            raise ValueError("minimum_gripper_width_m must be positive")
        if self.maximum_gripper_width_m <= self.minimum_gripper_width_m:
            raise ValueError(
                "maximum_gripper_width_m must exceed minimum_gripper_width_m"
            )
        if not 0.0 <= self.width_clearance_m < self.maximum_gripper_width_m:
            raise ValueError(
                "width_clearance_m must be non-negative and below maximum width"
            )
        if self.point_support_reference < self.minimum_points:
            raise ValueError(
                "point_support_reference must be at least minimum_points"
            )
        normalized_names = tuple(
            name.strip().lower() for name in self.upright_axisymmetric_class_names
        )
        if not normalized_names or any(not name for name in normalized_names):
            raise ValueError("upright_axisymmetric_class_names must not be empty")
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError("upright_axisymmetric_class_names must not contain duplicates")
        object.__setattr__(self, "upright_axisymmetric_class_names", normalized_names)
        if (
            not np.isfinite(self.upright_height_to_width_ratio)
            or self.upright_height_to_width_ratio <= 0.0
        ):
            raise ValueError("upright_height_to_width_ratio must be positive")
        if not 0.5 <= self.upright_grasp_height_quantile < 1.0:
            raise ValueError("upright_grasp_height_quantile must be in [0.5, 1)")


class PCATopGraspPlanner:
    """Produce one deterministic top-grasp candidate from perceived geometry.

    Grasp-frame axes expressed in world coordinates are:
    ``+X`` gripper closing axis, ``+Y`` finger / object-long axis, and
    ``+Z`` downward approach direction.
    """

    _SCORE_WEIGHTS = {
        "perception_confidence": 0.25,
        "depth_valid_ratio": 0.25,
        "point_support": 0.15,
        "geometric_compactness": 0.20,
        "width_margin": 0.15,
    }

    def __init__(self, config: PCATopGraspConfig | None = None) -> None:
        self._config = config or PCATopGraspConfig()

    def plan(self, target: LocalizedTarget) -> tuple[GraspCandidate, ...]:
        """Return a single scored candidate without robot-state or truth access."""

        points = np.asarray(target.points_world_m, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError(f"points_world_m must have shape (N, 3), got {points.shape}")
        if points.shape[0] < self._config.minimum_points:
            raise ValueError(
                f"point count below minimum: {points.shape[0]} < "
                f"{self._config.minimum_points}"
            )
        if not np.all(np.isfinite(points)):
            raise ValueError("points_world_m must contain only finite values")

        centroid = np.asarray(target.centroid_world_m, dtype=np.float64)
        if centroid.shape != (3,) or not np.all(np.isfinite(centroid)):
            raise ValueError("centroid_world_m must be a finite 3-vector")

        planar_points = points[:, :2]
        axisymmetric_fit = self._is_upright_axisymmetric(target, points)
        if axisymmetric_fit:
            fitted_center_xy, fitted_radius_m = self._fit_planar_circle(planar_points)
            long_axis_xy = np.array([0.0, 1.0], dtype=np.float64)
            circularity = 1.0
        else:
            fitted_center_xy = centroid[:2]
            fitted_radius_m = 0.0
            pca_points = self._radial_inliers(planar_points)
            long_axis_xy, circularity = self._long_axis(pca_points)

        approach_axis_world = np.array([0.0, 0.0, -1.0], dtype=np.float64)
        finger_axis_world = np.array(
            [long_axis_xy[0], long_axis_xy[1], 0.0], dtype=np.float64
        )
        closing_axis_world = np.cross(finger_axis_world, approach_axis_world)
        closing_axis_world /= np.linalg.norm(closing_axis_world)
        rotation = np.column_stack(
            (closing_axis_world, finger_axis_world, approach_axis_world)
        )
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-9) or not np.isclose(
            np.linalg.det(rotation), 1.0, atol=1e-9
        ):
            raise RuntimeError("constructed grasp rotation is not right-handed orthonormal")

        closing_projection = points @ closing_axis_world
        finger_projection = points @ finger_axis_world
        if axisymmetric_fit:
            object_width_m = 2.0 * fitted_radius_m
            object_length_m = object_width_m
        else:
            object_width_m = self._robust_span(closing_projection)
            object_length_m = self._robust_span(finger_projection)
        required_width_m = object_width_m + self._config.width_clearance_m
        width_feasible = required_width_m <= self._config.maximum_gripper_width_m
        commanded_width_m = float(
            np.clip(
                required_width_m,
                self._config.minimum_gripper_width_m,
                self._config.maximum_gripper_width_m,
            )
        )

        score_terms = self._score_terms(
            target=target,
            points=points,
            closing_projection=closing_projection,
            finger_projection=finger_projection,
            object_width_m=object_width_m,
            object_length_m=object_length_m,
            required_width_m=required_width_m,
            circularity=circularity,
        )
        score = sum(
            self._SCORE_WEIGHTS[name] * score_terms[name]
            for name in self._SCORE_WEIGHTS
        )
        if not width_feasible:
            score = 0.0

        world_from_grasp = np.eye(4, dtype=np.float64)
        world_from_grasp[:3, :3] = rotation
        world_from_grasp[:3, 3] = centroid
        if axisymmetric_fit:
            world_from_grasp[:2, 3] = fitted_center_xy
            world_from_grasp[2, 3] = float(
                np.quantile(points[:, 2], self._config.upright_grasp_height_quantile)
            )
        score_terms["axisymmetric_circle_fit"] = float(axisymmetric_fit)
        score_terms["grasp_height_m"] = float(world_from_grasp[2, 3])

        candidate = GraspCandidate(
            candidate_id=f"top-pca-{target.detection.class_id}-0",
            world_from_grasp=world_from_grasp,
            gripper_width_m=commanded_width_m,
            score=float(np.clip(score, 0.0, 1.0)),
            # At this stage, reachable means width-feasible only. Motion
            # reachability remains the control module's responsibility.
            reachable=bool(width_feasible),
            score_terms=score_terms,
        )
        return (candidate,)

    def _is_upright_axisymmetric(
        self, target: LocalizedTarget, points: NDArray[np.float64]
    ) -> bool:
        if (
            target.detection.class_name.lower()
            not in self._config.upright_axisymmetric_class_names
        ):
            return False
        planar_span_m = max(
            float(np.ptp(points[:, 0])),
            float(np.ptp(points[:, 1])),
        )
        height_m = float(np.ptp(points[:, 2]))
        return (
            planar_span_m > np.finfo(np.float64).eps
            and height_m
            >= self._config.upright_height_to_width_ratio * planar_span_m
        )

    @staticmethod
    def _fit_planar_circle(
        planar_points: NDArray[np.float64],
    ) -> tuple[NDArray[np.float64], float]:
        design = np.column_stack(
            (2.0 * planar_points, np.ones(planar_points.shape[0]))
        )
        squared_radius_terms = np.sum(planar_points * planar_points, axis=1)
        solution, _, rank, _ = np.linalg.lstsq(
            design, squared_radius_terms, rcond=None
        )
        if rank < 3:
            raise ValueError("upright object points are degenerate for circle fitting")
        center = np.asarray(solution[:2], dtype=np.float64)
        radius_squared = float(solution[2] + np.dot(center, center))
        if not np.all(np.isfinite(center)) or not np.isfinite(radius_squared):
            raise ValueError("circle fit produced non-finite geometry")
        if radius_squared <= np.finfo(np.float64).eps:
            raise ValueError("circle fit radius must be positive")
        return center, float(np.sqrt(radius_squared))

    def _radial_inliers(
        self, planar_points: NDArray[np.float64]
    ) -> NDArray[np.float64]:
        robust_center = np.median(planar_points, axis=0)
        radius_squared = np.sum((planar_points - robust_center) ** 2, axis=1)
        cutoff = float(
            np.quantile(radius_squared, self._config.pca_inlier_quantile)
        )
        # Include the entire cutoff shell. Symmetric shapes often contain
        # several points at mathematically identical radii whose floating-point
        # representations differ by a few ulps after rotation.
        inside = (radius_squared <= cutoff) | np.isclose(
            radius_squared,
            cutoff,
            rtol=1e-12,
            atol=1e-15,
        )
        inliers = planar_points[inside]
        if inliers.shape[0] < self._config.minimum_points:
            return planar_points
        return inliers

    def _long_axis(
        self, planar_points: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], float]:
        centered = planar_points - np.mean(planar_points, axis=0)
        covariance = centered.T @ centered / planar_points.shape[0]
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        order = np.argsort(eigenvalues)[::-1]
        major_variance = float(eigenvalues[order[0]])
        minor_variance = max(float(eigenvalues[order[1]]), 0.0)
        if major_variance < self._config.minimum_planar_variance_m2:
            raise ValueError("planar point cloud variance is too small for grasp planning")

        circularity = float(np.clip(minor_variance / major_variance, 0.0, 1.0))
        if circularity >= self._config.circularity_ratio_threshold:
            return np.array([1.0, 0.0], dtype=np.float64), circularity

        long_axis = np.asarray(eigenvectors[:, order[0]], dtype=np.float64)
        dominant_component = int(np.argmax(np.abs(long_axis)))
        if long_axis[dominant_component] < 0.0:
            long_axis = -long_axis
        long_axis /= np.linalg.norm(long_axis)
        return long_axis, circularity

    def _robust_span(self, projection: NDArray[np.float64]) -> float:
        lower, upper = np.quantile(
            projection,
            [
                self._config.extent_lower_quantile,
                self._config.extent_upper_quantile,
            ],
        )
        return max(float(upper - lower), 0.0)

    def _score_terms(
        self,
        *,
        target: LocalizedTarget,
        points: NDArray[np.float64],
        closing_projection: NDArray[np.float64],
        finger_projection: NDArray[np.float64],
        object_width_m: float,
        object_length_m: float,
        required_width_m: float,
        circularity: float,
    ) -> dict[str, float]:
        full_width_m = float(np.ptp(closing_projection))
        full_length_m = float(np.ptp(finger_projection))
        robust_area_m2 = object_width_m * object_length_m
        full_area_m2 = full_width_m * full_length_m
        compactness = (
            1.0
            if full_area_m2 <= np.finfo(np.float64).eps
            else float(np.clip(robust_area_m2 / full_area_m2, 0.0, 1.0))
        )
        width_range_m = (
            self._config.maximum_gripper_width_m
            - self._config.minimum_gripper_width_m
        )
        width_margin = float(
            np.clip(
                (self._config.maximum_gripper_width_m - required_width_m)
                / width_range_m,
                0.0,
                1.0,
            )
        )
        return {
            "perception_confidence": float(
                np.clip(target.detection.confidence, 0.0, 1.0)
            ),
            "depth_valid_ratio": float(np.clip(target.depth_valid_ratio, 0.0, 1.0)),
            "point_support": float(
                np.clip(
                    points.shape[0] / self._config.point_support_reference,
                    0.0,
                    1.0,
                )
            ),
            "geometric_compactness": compactness,
            "width_margin": width_margin,
            "estimated_object_width_m": float(object_width_m),
            "estimated_object_length_m": float(object_length_m),
            "required_width_m": float(required_width_m),
            "pca_circularity": float(circularity),
        }
