from __future__ import annotations

import unittest

import cv2
import numpy as np

from vision2grasp.contracts import RGBFrame
from vision2grasp.simulation import ProxyGeometry, extract_target_appearance
from vision2grasp.simulation.native_panda_validation import NativePandaValidation
from vision2grasp.target_perception import TargetInstance, TargetSceneSnapshot


def make_snapshot(label: str, mask: np.ndarray) -> TargetSceneSnapshot:
    height, width = mask.shape
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[...] = (238, 24, 18)  # scene background that must never enter the texture
    rgb[mask] = (34, 116, 214)
    rows, columns = np.nonzero(mask)
    rgb[rows[len(rows) // 3 : len(rows) // 3 + 1], columns[len(columns) // 3]] = (240, 218, 32)
    x1, x2 = int(columns.min()), int(columns.max()) + 1
    y1, y2 = int(rows.min()), int(rows.max()) + 1
    return TargetSceneSnapshot(
        "snapshot-appearance-1",
        RGBFrame(91, 7.25, "phone-frozen", rgb),
        TargetInstance(
            instance_id="target-appearance-1",
            mask=np.asarray(mask, dtype=np.bool_),
            bbox_xyxy=(float(x1), float(y1), float(x2), float(y2)),
            centroid_2d=(float(np.mean(columns)), float(np.mean(rows))),
            source_frame_id=91,
            source_timestamp_s=7.25,
            class_name=label,
            semantic_source="instance-segmentation",
        ),
    )


class TargetAppearanceTests(unittest.TestCase):
    def test_priority_object_labels_map_to_stable_visual_proxies(self) -> None:
        mask = np.zeros((96, 96), dtype=np.bool_)
        mask[18:78, 24:72] = True
        expected = {
            "package": ProxyGeometry.BOX,
            "bottle": ProxyGeometry.CYLINDER,
            "banana": ProxyGeometry.CAPSULE,
            "apple": ProxyGeometry.ELLIPSOID,
        }
        for label, geometry in expected.items():
            with self.subTest(label=label):
                appearance = extract_target_appearance(make_snapshot(label, mask), texture_side=96)
                self.assertEqual(appearance.proxy_geometry, geometry)
                self.assertEqual(appearance.texture_size, (96, 96))
                self.assertEqual(appearance.extraction_source, "LOCKED_SCENE_SNAPSHOT_RGB_PLUS_TARGET_MASK")
                self.assertEqual(appearance.public_metadata()["storage"], "SESSION_MEMORY")

    def test_mask_removes_scene_background_before_texture_mapping(self) -> None:
        mask = np.zeros((80, 120), dtype=np.bool_)
        cv2.ellipse(mask.view(np.uint8), (60, 40), (34, 22), 0, 0, 360, 1, -1)
        appearance = extract_target_appearance(make_snapshot("apple", mask), texture_side=128)
        decoded_bgr = cv2.imdecode(
            np.frombuffer(appearance.texture_png, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        self.assertIsNotNone(decoded_bgr)
        decoded_rgb = cv2.cvtColor(decoded_bgr, cv2.COLOR_BGR2RGB)
        background = np.array([238, 24, 18], dtype=np.uint8)
        self.assertFalse(np.any(np.all(decoded_rgb == background, axis=2)))
        self.assertTrue(appearance.public_metadata()["background_removed"])

    def test_unknown_rectangular_mask_uses_box_without_semantic_guessing(self) -> None:
        mask = np.zeros((80, 120), dtype=np.bool_)
        mask[18:62, 25:95] = True
        appearance = extract_target_appearance(make_snapshot("Unknown Object", mask))
        self.assertEqual(appearance.proxy_geometry, ProxyGeometry.BOX)

    def test_small_valid_mask_has_finite_shape_diagnostics(self) -> None:
        mask = np.zeros((16, 16), dtype=np.bool_)
        mask[8, 8] = True
        appearance = extract_target_appearance(make_snapshot("Unknown Object", mask), texture_side=32)
        self.assertTrue(np.isfinite(appearance.mask_elongation))
        self.assertEqual(appearance.foreground_pixel_count, 1)

    def test_visual_shell_never_changes_collision_contract(self) -> None:
        mask = np.zeros((96, 96), dtype=np.bool_)
        mask[12:84, 30:66] = True
        appearance = extract_target_appearance(make_snapshot("bottle", mask))
        attributes = NativePandaValidation._target_visual_attributes(
            np.array([0.03, 0.05, 0.07], dtype=np.float64), appearance
        )
        self.assertEqual(attributes["type"], "cylinder")
        self.assertEqual(attributes["material"], "target_appearance_material")
        # Collision flags are owned by the caller's fixed physics geom; the
        # appearance helper can only describe rendering attributes.
        self.assertNotIn("contype", attributes)
        self.assertNotIn("friction", attributes)
        self.assertNotIn("density", attributes)


if __name__ == "__main__":
    unittest.main()
