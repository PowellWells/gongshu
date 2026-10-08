from __future__ import annotations

from types import SimpleNamespace
import unittest

import cv2
import numpy as np

from vision2grasp.contracts import RGBFrame
from vision2grasp.simulation import (
    ProxyGeometry,
    ValidationSceneTransform,
    extract_target_appearance,
    reconstruct_object,
)
from vision2grasp.simulation.reconstruction_debug import (
    build_reconstruction_debug_bundle,
)
from vision2grasp.spatial_perception import DepthMode
from vision2grasp.target_perception import TargetInstance, TargetSceneSnapshot


def make_snapshot(mask: np.ndarray, label: str = "Unknown Object") -> TargetSceneSnapshot:
    rgb = np.zeros((*mask.shape, 3), dtype=np.uint8)
    rgb[...] = (22, 34, 48)
    rgb[mask] = (65, 156, 212)
    rows, columns = np.nonzero(mask)
    frame = RGBFrame(17, 4.5, "fixture", rgb)
    return TargetSceneSnapshot(
        "snapshot-reconstruction",
        frame,
        TargetInstance(
            instance_id="target-reconstruction",
            mask=mask,
            bbox_xyxy=(
                float(columns.min()),
                float(rows.min()),
                float(columns.max() + 1),
                float(rows.max() + 1),
            ),
            centroid_2d=(float(np.mean(columns)), float(np.mean(rows))),
            source_frame_id=frame.frame_id,
            source_timestamp_s=frame.timestamp_s,
            class_name=label,
        ),
    )


def observation(snapshot: TargetSceneSnapshot, points: np.ndarray):
    depth = np.full(snapshot.frame.rgb.shape[:2], 1.0, dtype=np.float32)
    return SimpleNamespace(
        snapshot_id=snapshot.snapshot_id,
        geometry_chain_id=snapshot.geometry_chain_id,
        source_frame_id=snapshot.frame.frame_id,
        target_instance_id=snapshot.target.instance_id,
        target_point_cloud=np.asarray(points, dtype=np.float32),
        centroid_xyz=np.mean(points, axis=0),
        depth_mode=DepthMode.METRIC,
        depth_frame=SimpleNamespace(values=depth),
    )


def box_points(extents: tuple[float, float, float], count: int = 18) -> np.ndarray:
    axes = [np.linspace(-value / 2.0, value / 2.0, count) for value in extents]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    grid[:, 2] += 1.0
    return grid


def cylinder_points(radius: float = 0.035, height: float = 0.16) -> np.ndarray:
    theta = np.linspace(0.0, 2.0 * np.pi, 80, endpoint=False)
    vertical = np.linspace(-height / 2.0, height / 2.0, 32)
    theta_grid, vertical_grid = np.meshgrid(theta, vertical)
    return np.column_stack(
        (
            radius * np.cos(theta_grid).ravel(),
            vertical_grid.ravel(),
            1.0 + radius * np.sin(theta_grid).ravel(),
        )
    )


class ObjectReconstructionTests(unittest.TestCase):
    def test_rotated_box_mask_does_not_become_cylinder(self) -> None:
        mask = np.zeros((180, 180), dtype=np.bool_)
        corners = cv2.boxPoints(((90.0, 85.0), (96.0, 58.0), 28.0)).round().astype(np.int32)
        cv2.fillConvexPoly(mask.view(np.uint8), corners, 1)
        snapshot = make_snapshot(mask, "Unknown Object")
        reconstruction = reconstruct_object(
            observation(snapshot, box_points((0.11, 0.06, 0.15))),
            snapshot,
            extract_target_appearance(snapshot),
        )
        self.assertGreater(
            extract_target_appearance(snapshot).mask_oriented_bbox_fill_ratio,
            0.84,
        )
        self.assertEqual(reconstruction.proxy_geometry, ProxyGeometry.BOX)

    def test_semantic_cylinder_does_not_override_box_point_cloud(self) -> None:
        mask = np.zeros((120, 120), dtype=np.bool_)
        mask[20:100, 25:95] = True
        snapshot = make_snapshot(mask, "bottle")
        reconstruction = reconstruct_object(
            observation(snapshot, box_points((0.11, 0.06, 0.15))),
            snapshot,
            extract_target_appearance(snapshot),
        )
        self.assertEqual(reconstruction.proxy_geometry, ProxyGeometry.BOX)

    def test_point_cloud_shapes_do_not_collapse_to_cylinder(self) -> None:
        cases = []
        rectangular = np.zeros((120, 120), dtype=np.bool_)
        rectangular[25:95, 20:100] = True
        cases.append(("box", rectangular, box_points((0.10, 0.05, 0.12)), ProxyGeometry.BOX))

        bottle = np.zeros((140, 100), dtype=np.bool_)
        bottle[20:125, 30:70] = True
        cases.append(("bottle", bottle, cylinder_points(), ProxyGeometry.CYLINDER))

        elongated = np.zeros((80, 180), dtype=np.bool_)
        cv2.ellipse(elongated.view(np.uint8), (90, 40), (72, 16), 0, 0, 360, 1, -1)
        cases.append(("Unknown Object", elongated, box_points((0.18, 0.04, 0.035)), ProxyGeometry.CAPSULE))

        rounded = np.zeros((100, 100), dtype=np.bool_)
        cv2.circle(rounded.view(np.uint8), (50, 50), 34, 1, -1)
        cases.append(("Unknown Object", rounded, box_points((0.08, 0.075, 0.08)), ProxyGeometry.ELLIPSOID))

        for label, mask, points, expected in cases:
            with self.subTest(expected=expected.value):
                snapshot = make_snapshot(mask, label)
                reconstruction = reconstruct_object(
                    observation(snapshot, points),
                    snapshot,
                    extract_target_appearance(snapshot),
                )
                self.assertEqual(reconstruction.proxy_geometry, expected)
                self.assertTrue(reconstruction.is_point_cloud_driven)

    def test_camera_optical_depth_is_not_used_as_world_height(self) -> None:
        mask = np.zeros((140, 100), dtype=np.bool_)
        mask[15:125, 30:70] = True
        snapshot = make_snapshot(mask)
        reconstruction = reconstruct_object(
            observation(snapshot, box_points((0.06, 0.14, 0.02))),
            snapshot,
            extract_target_appearance(snapshot),
        )
        self.assertGreater(
            reconstruction.proxy_extents_world_xyz[2],
            reconstruction.proxy_extents_world_xyz[1],
        )

    def test_proxy_geometry_and_object_yaw_are_grasp_independent(self) -> None:
        mask = np.zeros((120, 120), dtype=np.bool_)
        mask[20:100, 25:95] = True
        snapshot = make_snapshot(mask)
        reconstruction = reconstruct_object(
            observation(snapshot, box_points((0.11, 0.05, 0.13))),
            snapshot,
            extract_target_appearance(snapshot),
        )
        first = SimpleNamespace(
            object_extents_xyz=np.array([0.02, 0.02, 0.02]),
            grasp_point_xyz=reconstruction.centroid_camera_xyz,
            grasp_angle=0.1,
        )
        second = SimpleNamespace(
            object_extents_xyz=np.array([0.20, 0.20, 0.20]),
            grasp_point_xyz=reconstruction.centroid_camera_xyz,
            grasp_angle=1.2,
        )
        first_scene = ValidationSceneTransform.from_grasp_plan(
            first, object_reconstruction=reconstruction
        )
        second_scene = ValidationSceneTransform.from_grasp_plan(
            second, object_reconstruction=reconstruction
        )
        np.testing.assert_allclose(first_scene.target_extents_world, second_scene.target_extents_world)
        self.assertAlmostEqual(first_scene.target_yaw_rad, second_scene.target_yaw_rad)
        self.assertFalse(np.allclose(first_scene.closing_world, second_scene.closing_world))

    def test_debug_bundle_contains_four_frozen_views_from_one_chain(self) -> None:
        mask = np.zeros((96, 96), dtype=np.bool_)
        mask[18:78, 24:72] = True
        snapshot = make_snapshot(mask)
        obs = observation(snapshot, box_points((0.08, 0.04, 0.11)))
        reconstruction = reconstruct_object(obs, snapshot, extract_target_appearance(snapshot))
        bundle = build_reconstruction_debug_bundle(snapshot, obs, reconstruction)
        self.assertEqual(bundle.metadata["geometry_chain_id"], snapshot.geometry_chain_id)
        self.assertEqual(set(bundle.frames), {"input", "mask", "point-cloud", "proxy"})
        self.assertTrue(all(len(payload) > 500 for payload in bundle.frames.values()))


if __name__ == "__main__":
    unittest.main()
