from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

import cv2
import numpy as np

from vision2grasp import CameraIntrinsics, RGBDFrame
from vision2grasp.perception import UltralyticsYOLOSegmenter


ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "artifacts" / "models" / "yolo11n-seg.pt"
BOTTLE_IMAGE = ROOT / "artifacts" / "perception" / "bottle_cc0.jpg"
BOTTLE_IMAGE_SHA256 = "7e43c9fc4ac3b658bd7daf2e916d078ae6051bc21b472cd229184f48fe624585"
# CC0 source: https://commons.wikimedia.org/wiki/File:Fiji_water_bottle.jpg


@unittest.skipUnless(
    WEIGHTS.is_file() and BOTTLE_IMAGE.is_file(),
    "official YOLO weights and CC0 bottle smoke-test image are required",
)
class PerceptionIntegrationTests(unittest.TestCase):
    def test_official_yolo11n_seg_detects_bottle_with_original_scale_mask(self) -> None:
        self.assertEqual(
            hashlib.sha256(BOTTLE_IMAGE.read_bytes()).hexdigest(),
            BOTTLE_IMAGE_SHA256,
        )
        bgr = cv2.imread(str(BOTTLE_IMAGE), cv2.IMREAD_COLOR)
        self.assertIsNotNone(bgr)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        frame = RGBDFrame(
            frame_id=0,
            timestamp_s=0.0,
            camera_name="smoke-test",
            rgb=rgb,
            depth_m=np.ones((height, width), dtype=np.float32),
            intrinsics=CameraIntrinsics(
                width=width,
                height=height,
                fx=float(width),
                fy=float(width),
                cx=width / 2,
                cy=height / 2,
            ),
            world_from_camera=np.eye(4, dtype=np.float64),
        )

        detections = UltralyticsYOLOSegmenter().predict(frame)

        self.assertTrue(detections)
        self.assertTrue(all(item.class_name in {"bottle", "cup"} for item in detections))
        self.assertTrue(any(item.class_name == "bottle" for item in detections))
        for detection in detections:
            self.assertEqual(detection.mask.shape, (height, width))
            self.assertEqual(detection.mask.dtype, np.bool_)
            self.assertGreater(int(detection.mask.sum()), 0)


if __name__ == "__main__":
    unittest.main()
