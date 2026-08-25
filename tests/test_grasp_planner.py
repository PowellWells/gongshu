from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import numpy as np

from vision2grasp import Detection2D, LocalizedTarget
from vision2grasp.grasp import PCATopGraspConfig, PCATopGraspPlanner


ROOT = Path(__file__).resolve().parents[1]


def rectangle_points(
    *,
    length_m: float,
    width_m: float,
    angle_degrees: float,
    center: tuple[float, float, float] = (0.1, -0.2, 0.8),
) -> np.ndarray:
    long_values = np.linspace(-length_m / 2, length_m / 2, 25)
    short_values = np.linspace(-width_m / 2, width_m / 2, 11)
    long_grid, short_grid = np.meshgrid(long_values, short_values)
    angle = np.deg2rad(angle_degrees)
    long_axis = np.array([np.cos(angle), np.sin(angle)])
    short_axis = np.array([-np.sin(angle), np.cos(angle)])
    xy = (
        np.asarray(center[:2])
        + long_grid.reshape(-1, 1) * long_axis
        + short_grid.reshape(-1, 1) * short_axis
    )
    z = np.full((xy.shape[0], 1), center[2])
    return np.hstack((xy, z)).astype(np.float64)


def make_target(
    points: np.ndarray,
    *,
    confidence: float = 0.9,
    depth_valid_ratio: float = 0.95,
    centroid: np.ndarray | None = None,
) -> LocalizedTarget:
    detection = Detection2D(
        class_id=39,
        class_name="bottle",
        confidence=confidence,
        bbox_xyxy=(0.0, 0.0, 1.0, 1.0),
        mask=np.ones((1, 1), dtype=np.bool_),
    )
    return LocalizedTarget(
        detection=detection,
        centroid_world_m=(
            np.mean(points, axis=0).astype(np.float64)
            if centroid is None
            else np.asarray(centroid, dtype=np.float64)
        ),
        points_world_m=np.asarray(points, dtype=np.float64),
        depth_valid_ratio=depth_valid_ratio,
    )


class PCATopGraspPlannerTests(unittest.TestCase):
    def test_rotated_rectangle_produces_expected_top_grasp_axes_and_width(self) -> None:
        points = rectangle_points(
            length_m=0.12,
            width_m=0.04,
            angle_degrees=30.0,
        )
        target = make_target(points)
        planner = PCATopGraspPlanner()

        candidate = planner.plan(target)[0]

        rotation = candidate.world_from_grasp[:3, :3]
        expected_long_axis = np.array(
            [np.cos(np.deg2rad(30.0)), np.sin(np.deg2rad(30.0)), 0.0]
        )
        expected_closing_axis = np.array(
            [-np.sin(np.deg2rad(30.0)), np.cos(np.deg2rad(30.0)), 0.0]
        )
        np.testing.assert_allclose(rotation[:, 0], expected_closing_axis, atol=1e-7)
        np.testing.assert_allclose(rotation[:, 1], expected_long_axis, atol=1e-7)
        np.testing.assert_allclose(rotation[:, 2], [0.0, 0.0, -1.0])
        np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-9)
        self.assertAlmostEqual(float(np.linalg.det(rotation)), 1.0)
        np.testing.assert_allclose(
            candidate.world_from_grasp[:3, 3], target.centroid_world_m
        )
        self.assertAlmostEqual(candidate.gripper_width_m, 0.048, places=6)
        self.assertTrue(candidate.reachable)
        self.assertGreater(candidate.score, 0.0)

    def test_planning_is_deterministic_and_canonicalizes_axis_sign(self) -> None:
        points = rectangle_points(
            length_m=0.10,
            width_m=0.03,
            angle_degrees=150.0,
        )
        planner = PCATopGraspPlanner()
        target = make_target(points)

        first = planner.plan(target)[0]
        second = planner.plan(target)[0]

        np.testing.assert_array_equal(first.world_from_grasp, second.world_from_grasp)
        self.assertEqual(first.score_terms, second.score_terms)
        long_axis = first.world_from_grasp[:2, 1]
        dominant_component = int(np.argmax(np.abs(long_axis)))
        self.assertGreater(long_axis[dominant_component], 0.0)

    def test_near_circular_cloud_uses_fixed_world_axis_fallback(self) -> None:
        angles = np.linspace(0.0, 2.0 * np.pi, 360, endpoint=False)
        points = np.column_stack(
            (
                0.03 * np.cos(angles),
                0.03 * np.sin(angles),
                np.full(angles.shape, 0.8),
            )
        )

        candidate = PCATopGraspPlanner().plan(make_target(points))[0]

        np.testing.assert_allclose(
            candidate.world_from_grasp[:3, 1], [1.0, 0.0, 0.0]
        )
        np.testing.assert_allclose(
            candidate.world_from_grasp[:3, 0], [0.0, 1.0, 0.0]
        )
        self.assertGreaterEqual(
            candidate.score_terms["pca_circularity"], 0.99
        )
        self.assertTrue(candidate.reachable)

    def test_upright_bottle_uses_circle_center_and_upper_grasp_height(self) -> None:
        angles = np.linspace(-np.pi / 2.0, np.pi / 2.0, 30)
        heights = np.linspace(0.82, 0.98, 20)
        angle_grid, height_grid = np.meshgrid(angles, heights)
        center_xy = np.array([0.015, -0.01])
        radius_m = 0.025
        points = np.column_stack(
            (
                center_xy[0] + radius_m * np.cos(angle_grid).reshape(-1),
                center_xy[1] + radius_m * np.sin(angle_grid).reshape(-1),
                height_grid.reshape(-1),
            )
        )

        candidate = PCATopGraspPlanner().plan(make_target(points))[0]

        np.testing.assert_allclose(candidate.world_from_grasp[:2, 3], center_xy)
        self.assertAlmostEqual(
            candidate.world_from_grasp[2, 3],
            float(np.quantile(points[:, 2], 0.75)),
        )
        self.assertAlmostEqual(candidate.gripper_width_m, 0.058)
        self.assertEqual(candidate.score_terms["axisymmetric_circle_fit"], 1.0)

    def test_spatial_outliers_do_not_rotate_axis_or_inflate_robust_width(self) -> None:
        clean_points = rectangle_points(
            length_m=0.10,
            width_m=0.03,
            angle_degrees=20.0,
        )
        outliers = np.array([[3.0, 4.0, 0.8], [-4.0, 3.0, 0.8]])
        planner = PCATopGraspPlanner()

        clean = planner.plan(make_target(clean_points))[0]
        noisy = planner.plan(make_target(np.vstack((clean_points, outliers))))[0]

        alignment = abs(
            float(
                np.dot(
                    clean.world_from_grasp[:2, 1],
                    noisy.world_from_grasp[:2, 1],
                )
            )
        )
        self.assertGreater(alignment, 0.999)
        self.assertLess(noisy.score_terms["estimated_object_width_m"], 0.05)
        self.assertLess(
            noisy.score_terms["geometric_compactness"],
            clean.score_terms["geometric_compactness"],
        )

    def test_oversized_object_returns_zero_score_unreachable_candidate(self) -> None:
        points = rectangle_points(
            length_m=0.14,
            width_m=0.10,
            angle_degrees=0.0,
        )

        candidate = PCATopGraspPlanner().plan(make_target(points))[0]

        self.assertFalse(candidate.reachable)
        self.assertEqual(candidate.gripper_width_m, 0.08)
        self.assertEqual(candidate.score, 0.0)
        self.assertGreater(candidate.score_terms["required_width_m"], 0.08)
        self.assertEqual(candidate.score_terms["width_margin"], 0.0)

    def test_rejects_insufficient_nonfinite_and_degenerate_geometry(self) -> None:
        planner = PCATopGraspPlanner()
        too_few = np.zeros((29, 3), dtype=np.float64)
        with self.assertRaisesRegex(ValueError, "point count below minimum"):
            planner.plan(make_target(too_few))

        nonfinite = rectangle_points(
            length_m=0.10, width_m=0.03, angle_degrees=0.0
        )
        nonfinite[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "finite"):
            planner.plan(make_target(nonfinite, centroid=np.zeros(3)))

        vertical_line = np.column_stack(
            (
                np.zeros(30),
                np.zeros(30),
                np.linspace(0.7, 0.9, 30),
            )
        )
        with self.assertRaisesRegex(ValueError, "variance is too small"):
            planner.plan(make_target(vertical_line))


class PCATopGraspConfigTests(unittest.TestCase):
    def test_rejects_invalid_width_and_quantiles(self) -> None:
        with self.assertRaisesRegex(ValueError, "maximum_gripper_width_m"):
            PCATopGraspConfig(
                minimum_gripper_width_m=0.08,
                maximum_gripper_width_m=0.08,
            )
        with self.assertRaisesRegex(ValueError, "pca_inlier_quantile"):
            PCATopGraspConfig(pca_inlier_quantile=0.5)

    def test_default_toml_freezes_grasp_settings(self) -> None:
        with (ROOT / "configs" / "default.toml").open("rb") as handle:
            grasp = tomllib.load(handle)["grasp"]
        config = PCATopGraspConfig()
        self.assertEqual(grasp["strategy"], "top_grasp_pca")
        self.assertFalse(grasp["use_simulation_truth"])
        for key in (
            "minimum_points",
            "pca_inlier_quantile",
            "extent_lower_quantile",
            "extent_upper_quantile",
            "circularity_ratio_threshold",
            "minimum_planar_variance_m2",
            "minimum_gripper_width_m",
            "maximum_gripper_width_m",
            "width_clearance_m",
            "point_support_reference",
            "upright_height_to_width_ratio",
            "upright_grasp_height_quantile",
        ):
            self.assertEqual(grasp[key], getattr(config, key))
        self.assertEqual(
            grasp["upright_axisymmetric_class_names"],
            list(config.upright_axisymmetric_class_names),
        )


if __name__ == "__main__":
    unittest.main()
