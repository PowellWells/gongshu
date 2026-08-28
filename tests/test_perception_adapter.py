from __future__ import annotations

import hashlib
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from vision2grasp import CameraIntrinsics, RGBDFrame
from vision2grasp.perception import (
    UltralyticsSegmenterConfig,
    UltralyticsYOLOSegmenter,
)


ROOT = Path(__file__).resolve().parents[1]


def make_frame() -> RGBDFrame:
    rgb = np.empty((3, 4, 3), dtype=np.uint8)
    rgb[..., 0] = 10
    rgb[..., 1] = 20
    rgb[..., 2] = 30
    return RGBDFrame(
        frame_id=1,
        timestamp_s=0.0,
        camera_name="agentview",
        rgb=rgb,
        depth_m=np.ones((3, 4), dtype=np.float32),
        intrinsics=CameraIntrinsics(4, 3, 100.0, 100.0, 2.0, 1.5),
        world_from_camera=np.eye(4, dtype=np.float64),
    )


class FakeModel:
    task = "segment"

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def predict(self, **kwargs: object) -> list[object]:
        self.calls.append(kwargs)
        return [self.result]


class PerceptionAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.weights_path = root / "yolo11n-seg.pt"
        self.weights_path.write_bytes(b"test-weights")
        self.digest = hashlib.sha256(b"test-weights").hexdigest()
        self.config_dir = root / "config"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def config(self, **overrides: object) -> UltralyticsSegmenterConfig:
        values: dict[str, object] = {
            "weights_path": self.weights_path,
            "weights_sha256": self.digest,
            "target_class_names": ("bottle", "cup"),
            "ultralytics_config_dir": self.config_dir,
        }
        values.update(overrides)
        return UltralyticsSegmenterConfig(**values)  # type: ignore[arg-type]

    def test_converts_original_scale_masks_and_filters_classes(self) -> None:
        boxes = SimpleNamespace(
            xyxy=np.array(
                [
                    [-1.0, 0.0, 3.0, 3.0],
                    [0.0, 0.0, 4.0, 3.0],
                    [1.0, 1.0, 4.0, 3.0],
                ]
            ),
            conf=np.array([0.90, 0.95, 0.40]),
            cls=np.array([39.0, 0.0, 41.0]),
        )
        masks = SimpleNamespace(
            data=np.array(
                [
                    [
                        [0.0, 0.6, 0.6, 0.0],
                        [0.0, 0.9, 0.9, 0.0],
                        [0.0, 0.0, 0.0, 0.0],
                    ],
                    np.ones((3, 4)),
                    np.ones((3, 4)),
                ]
            )
        )
        result = SimpleNamespace(
            boxes=boxes,
            masks=masks,
            names={0: "person", 39: "bottle", 41: "cup"},
        )
        model = FakeModel(result)
        segmenter = UltralyticsYOLOSegmenter(self.config())

        with patch(
            "vision2grasp.perception.ultralytics_adapter._load_yolo_model",
            return_value=model,
        ) as loader:
            detections = segmenter.predict(make_frame())
            segmenter.predict(make_frame())

        loader.assert_called_once()
        self.assertEqual(segmenter.model_name, "yolo11n-seg")
        self.assertEqual(len(detections), 1)
        detection = detections[0]
        self.assertEqual(detection.class_id, 39)
        self.assertEqual(detection.class_name, "bottle")
        self.assertEqual(detection.bbox_xyxy, (0.0, 0.0, 3.0, 3.0))
        self.assertEqual(detection.mask.dtype, np.bool_)
        self.assertEqual(int(detection.mask.sum()), 4)

        call = model.calls[0]
        np.testing.assert_array_equal(
            call["source"], np.full((3, 4, 3), [30, 20, 10], dtype=np.uint8)
        )
        self.assertEqual(call["device"], "cpu")
        self.assertTrue(call["retina_masks"])
        self.assertFalse(call["save"])

    def test_empty_result_returns_empty_tuple(self) -> None:
        result = SimpleNamespace(
            boxes=SimpleNamespace(
                xyxy=np.empty((0, 4)), conf=np.empty(0), cls=np.empty(0)
            ),
            masks=None,
            names={},
        )
        segmenter = UltralyticsYOLOSegmenter(self.config())
        with patch(
            "vision2grasp.perception.ultralytics_adapter._load_yolo_model",
            return_value=FakeModel(result),
        ):
            self.assertEqual(segmenter.predict(make_frame()), ())

    def test_boxes_without_masks_are_rejected(self) -> None:
        result = SimpleNamespace(
            boxes=SimpleNamespace(
                xyxy=np.array([[0.0, 0.0, 2.0, 2.0]]),
                conf=np.array([0.9]),
                cls=np.array([39.0]),
            ),
            masks=None,
            names={39: "bottle"},
        )
        segmenter = UltralyticsYOLOSegmenter(self.config())
        with patch(
            "vision2grasp.perception.ultralytics_adapter._load_yolo_model",
            return_value=FakeModel(result),
        ):
            with self.assertRaisesRegex(RuntimeError, "without instance masks"):
                segmenter.predict(make_frame())

    def test_missing_and_tampered_weights_fail_before_model_load(self) -> None:
        missing = UltralyticsYOLOSegmenter(
            self.config(weights_path=self.weights_path.with_name("missing.pt"))
        )
        with self.assertRaises(FileNotFoundError):
            missing.predict(make_frame())

        tampered = UltralyticsYOLOSegmenter(self.config(weights_sha256="0" * 64))
        with patch(
            "vision2grasp.perception.ultralytics_adapter._load_yolo_model"
        ) as loader:
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                tampered.predict(make_frame())
            loader.assert_not_called()

    def test_public_adapter_does_not_expose_training(self) -> None:
        segmenter = UltralyticsYOLOSegmenter(self.config())
        self.assertFalse(hasattr(segmenter, "train"))
        self.assertFalse(hasattr(segmenter, "model"))


class PerceptionConfigTests(unittest.TestCase):
    def test_rejects_invalid_threshold_device_and_class_filter(self) -> None:
        with self.assertRaisesRegex(ValueError, "confidence_threshold"):
            UltralyticsSegmenterConfig(confidence_threshold=0.0)
        with self.assertRaisesRegex(ValueError, "device"):
            UltralyticsSegmenterConfig(device="cuda")
        with self.assertRaisesRegex(ValueError, "duplicates"):
            UltralyticsSegmenterConfig(target_class_names=("bottle", "Bottle"))

    def test_project_config_and_dependency_versions_are_frozen(self) -> None:
        with (ROOT / "configs" / "default.toml").open("rb") as handle:
            config = tomllib.load(handle)
        perception = config["perception"]
        self.assertEqual(perception["weights"], "artifacts/models/yolo11n-seg.pt")
        self.assertEqual(perception["device"], "cpu")
        self.assertEqual(perception["target_classes"], ["bottle", "cup"])
        self.assertFalse(perception["training_enabled"])

        with (ROOT / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)["project"]
        self.assertIn("torch==2.13.0", project["dependencies"])
        self.assertIn("torchvision==0.28.0", project["dependencies"])
        self.assertIn("ultralytics==8.4.128", project["dependencies"])


if __name__ == "__main__":
    unittest.main()
