from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

import numpy as np

from vision2grasp import CameraIntrinsics, Detection2D, RGBDFrame
from vision2grasp.geometry import (
    MaskDepthLocalizerConfig,
    MaskDepthTargetLocalizer,
)


ROOT = Path(__file__).resolve().parents[1]


def make_frame(
    depth_m: np.ndarray,
    *,
    fx: float = 1.0,
    fy: float = 1.0,
    cx: float = 0.0,
    cy: float = 0.0,
    world_from_camera: np.ndarray | None = None,
) -> RGBDFrame:
    height, width = depth_m.shape
    return RGBDFrame(
        frame_id=0,
        timestamp_s=0.0,
        camera_name="synthetic",
        rgb=np.zeros((height, width, 3), dtype=np.uint8),
        depth_m=np.asarray(depth_m, dtype=np.float32),
        intrinsics=CameraIntrinsics(width, height, fx, fy, cx, cy),
        world_from_camera=(
            np.eye(4, dtype=np.float64)
            if world_from_camera is None
            else np.asarray(world_from_camera, dtype=np.float64)
        ),
    )


def make_detection(mask: np.ndarray) -> Detection2D:
    rows, columns = np.nonzero(mask)
    if rows.size == 0:
        bbox = (0.0, 0.0, 1.0, 1.0)
    else:
        bbox = (
            float(columns.min()),
            float(rows.min()),
            float(columns.max() + 1),
            float(rows.max() + 1),
        )
    return Detection2D(
        class_id=39,
        class_name="bottle",
        confidence=0.9,
        bbox_xyxy=bbox,
        mask=np.asarray(mask, dtype=np.bool_),
    )


class MaskDepthLocalizerTests(unittest.TestCase):
    def test_backprojects_pixels_in_opencv_camera_coordinates(self) -> None:
        depth = np.full((3, 3), np.nan, dtype=np.float32)
        depth[1, 1:3] = 2.0
        mask = np.zeros((3, 3), dtype=np.bool_)
        mask[1, 1:3] = True
        frame = make_frame(depth, cx=1.0, cy=1.0)
        localizer = MaskDepthTargetLocalizer(
            MaskDepthLocalizerConfig(minimum_points=2, maximum_points=10)
        )

        target = localizer.localize(frame, make_detection(mask))

        np.testing.assert_allclose(
            target.points_world_m,
            [[0.0, 0.0, 2.0], [2.0, 0.0, 2.0]],
        )
        np.testing.assert_allclose(target.centroid_world_m, [1.0, 0.0, 2.0])
        self.assertEqual(target.depth_valid_ratio, 1.0)

    def test_applies_world_from_camera_rotation_and_translation(self) -> None:
        transform = np.array(
            [
                [0.0, -1.0, 0.0, 1.0],
                [1.0, 0.0, 0.0, 2.0],
                [0.0, 0.0, 1.0, 3.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        depth = np.full((2, 3), np.nan, dtype=np.float32)
        depth[1, 2] = 2.0
        mask = np.zeros((2, 3), dtype=np.bool_)
        mask[1, 2] = True
        frame = make_frame(
            depth,
            cx=1.0,
            cy=1.0,
            world_from_camera=transform,
        )
        localizer = MaskDepthTargetLocalizer(
            MaskDepthLocalizerConfig(minimum_points=1, maximum_points=1)
        )

        target = localizer.localize(frame, make_detection(mask))

        np.testing.assert_allclose(target.points_world_m, [[1.0, 4.0, 5.0]])
        np.testing.assert_allclose(target.centroid_world_m, [1.0, 4.0, 5.0])

    def test_rejects_low_valid_ratio_and_reports_ratio_before_filtering(self) -> None:
        mask = np.ones((1, 5), dtype=np.bool_)
        depth = np.array([[1.0, 1.0, 100.0, 1.0, np.nan]], dtype=np.float32)
        localizer = MaskDepthTargetLocalizer(
            MaskDepthLocalizerConfig(
                minimum_valid_depth_ratio=0.50,
                minimum_points=3,
                maximum_points=10,
            )
        )

        target = localizer.localize(make_frame(depth), make_detection(mask))

        self.assertAlmostEqual(target.depth_valid_ratio, 0.8)
        self.assertEqual(target.points_world_m.shape, (3, 3))
        np.testing.assert_allclose(target.points_world_m[:, 2], 1.0)
        self.assertAlmostEqual(float(target.centroid_world_m[2]), 1.0)

        invalid_depth = np.array([[1.0, np.nan, 0.0, -1.0]], dtype=np.float32)
        with self.assertRaisesRegex(ValueError, "valid depth ratio below minimum"):
            localizer.localize(
                make_frame(invalid_depth),
                make_detection(np.ones((1, 4), dtype=np.bool_)),
            )

    def test_sampling_is_deterministic_and_centroid_uses_all_inliers(self) -> None:
        depth = np.ones((10, 10), dtype=np.float32)
        mask = np.ones((10, 10), dtype=np.bool_)
        localizer = MaskDepthTargetLocalizer(
            MaskDepthLocalizerConfig(minimum_points=1, maximum_points=10)
        )
        frame = make_frame(depth, cx=5.0, cy=5.0)
        detection = make_detection(mask)

        first = localizer.localize(frame, detection)
        second = localizer.localize(frame, detection)

        self.assertEqual(first.points_world_m.shape, (10, 3))
        np.testing.assert_array_equal(first.points_world_m, second.points_world_m)
        np.testing.assert_allclose(first.centroid_world_m, [-0.5, -0.5, 1.0])

    def test_rejects_empty_mismatched_masks_and_nonrigid_transform(self) -> None:
        frame = make_frame(np.ones((2, 2), dtype=np.float32))
        localizer = MaskDepthTargetLocalizer(
            MaskDepthLocalizerConfig(minimum_points=1, maximum_points=10)
        )
        with self.assertRaisesRegex(ValueError, "at least one pixel"):
            localizer.localize(
                frame, make_detection(np.zeros((2, 2), dtype=np.bool_))
            )
        with self.assertRaisesRegex(ValueError, "must have shape"):
            localizer.localize(
                frame, make_detection(np.ones((1, 2), dtype=np.bool_))
            )

        nonrigid = np.eye(4)
        nonrigid[0, 0] = 2.0
        with self.assertRaisesRegex(ValueError, "orthonormal"):
            localizer.localize(
                make_frame(np.ones((2, 2)), world_from_camera=nonrigid),
                make_detection(np.ones((2, 2), dtype=np.bool_)),
            )


class GeometryConfigTests(unittest.TestCase):
    def test_rejects_invalid_limits(self) -> None:
        with self.assertRaisesRegex(ValueError, "minimum_valid_depth_ratio"):
            MaskDepthLocalizerConfig(minimum_valid_depth_ratio=0.0)
        with self.assertRaisesRegex(ValueError, "at least minimum_points"):
            MaskDepthLocalizerConfig(minimum_points=10, maximum_points=9)

    def test_default_toml_freezes_geometry_settings(self) -> None:
        with (ROOT / "configs" / "default.toml").open("rb") as handle:
            geometry = tomllib.load(handle)["geometry"]
        config = MaskDepthLocalizerConfig()
        self.assertEqual(
            geometry["minimum_valid_depth_ratio"],
            config.minimum_valid_depth_ratio,
        )
        self.assertEqual(geometry["minimum_points"], config.minimum_points)
        self.assertEqual(geometry["maximum_points"], config.maximum_points)
        self.assertEqual(geometry["outlier_mad_scale"], config.outlier_mad_scale)
        self.assertEqual(
            geometry["minimum_depth_band_m"], config.minimum_depth_band_m
        )


if __name__ == "__main__":
    unittest.main()

