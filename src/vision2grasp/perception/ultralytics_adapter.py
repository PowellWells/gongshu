"""Ultralytics YOLO11 instance-segmentation adapter."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np

from vision2grasp.contracts import Detection2D, RGBDFrame, RGBFrame


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_WEIGHTS = _PROJECT_ROOT / "artifacts" / "models" / "yolo11n-seg.pt"
_DEFAULT_CONFIG_DIR = _PROJECT_ROOT / "artifacts" / "ultralytics" / "config"
_YOLO11N_SEG_SHA256 = "55ed65c56c91713d23e8402371c6c49a6fd84f257f7dce452e8d70e41dcbe152"


@dataclass(frozen=True, slots=True)
class UltralyticsSegmenterConfig:
    """Configuration for deterministic CPU-only YOLO11n-seg inference."""

    weights_path: Path = _DEFAULT_WEIGHTS
    weights_sha256: str | None = _YOLO11N_SEG_SHA256
    confidence_threshold: float = 0.50
    mask_threshold: float = 0.50
    image_size: int = 640
    target_class_names: tuple[str, ...] | None = ("bottle", "cup")
    device: str = "cpu"
    ultralytics_config_dir: Path = _DEFAULT_CONFIG_DIR

    def __post_init__(self) -> None:
        object.__setattr__(self, "weights_path", Path(self.weights_path))
        object.__setattr__(
            self, "ultralytics_config_dir", Path(self.ultralytics_config_dir)
        )
        if not 0.0 < self.confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in (0, 1]")
        if not 0.0 < self.mask_threshold < 1.0:
            raise ValueError("mask_threshold must be in (0, 1)")
        if self.image_size <= 0:
            raise ValueError("image_size must be positive")
        if self.device != "cpu":
            raise ValueError("the stage-2 segmenter is frozen to device='cpu'")
        if self.target_class_names is not None:
            normalized = tuple(name.strip().lower() for name in self.target_class_names)
            if not normalized or any(not name for name in normalized):
                raise ValueError("target_class_names must contain non-empty names")
            if len(set(normalized)) != len(normalized):
                raise ValueError("target_class_names must not contain duplicates")
            object.__setattr__(self, "target_class_names", normalized)
        if self.weights_sha256 is not None:
            digest = self.weights_sha256.strip().lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("weights_sha256 must be a 64-character hexadecimal digest")
            object.__setattr__(self, "weights_sha256", digest)


class _YOLOModel(Protocol):
    task: str

    def predict(self, **kwargs: Any) -> Sequence[Any]: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yolo_model(config: UltralyticsSegmenterConfig) -> _YOLOModel:
    """Load Ultralytics lazily and isolate its settings inside this project."""

    config_dir = config.ultralytics_config_dir.resolve()
    config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(config_dir))

    from ultralytics import YOLO
    from ultralytics.utils import SETTINGS

    SETTINGS.update({"sync": False})
    model = YOLO(str(config.weights_path), task="segment")
    if model.task != "segment":
        raise ValueError(
            f"weights must provide instance segmentation, got task={model.task!r}"
        )
    return cast(_YOLOModel, model)


def _as_numpy(value: Any) -> np.ndarray:
    """Convert NumPy-like or torch-like inference output without importing torch."""

    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


class UltralyticsYOLOSegmenter:
    """Convert YOLO11n-seg predictions into pipeline ``Detection2D`` objects."""

    def __init__(self, config: UltralyticsSegmenterConfig | None = None) -> None:
        self._config = config or UltralyticsSegmenterConfig()
        self._model: _YOLOModel | None = None
        self._target_class_names = (
            None
            if self._config.target_class_names is None
            else frozenset(self._config.target_class_names)
        )

    @property
    def model_name(self) -> str:
        return self._config.weights_path.stem

    def predict(self, frame: RGBFrame | RGBDFrame) -> Sequence[Detection2D]:
        """Run CPU inference and return detections in the original RGB frame size."""

        model = self._ensure_model()
        # Ultralytics treats NumPy inputs as OpenCV BGR images.
        bgr = np.ascontiguousarray(frame.rgb[..., ::-1])
        results = model.predict(
            source=bgr,
            conf=self._config.confidence_threshold,
            imgsz=self._config.image_size,
            device=self._config.device,
            retina_masks=True,
            verbose=False,
            save=False,
        )
        if len(results) != 1:
            raise RuntimeError(
                f"single-frame inference must return one result, got {len(results)}"
            )
        return self._convert_result(results[0], frame)

    def _ensure_model(self) -> _YOLOModel:
        if self._model is not None:
            return self._model

        weights_path = self._config.weights_path
        if not weights_path.is_file():
            raise FileNotFoundError(
                f"YOLO weights not found at {weights_path}. "
                "Download the official yolo11n-seg.pt before inference."
            )
        expected_digest = self._config.weights_sha256
        if expected_digest is not None:
            actual_digest = _sha256(weights_path)
            if actual_digest != expected_digest:
                raise ValueError(
                    "YOLO weights SHA-256 mismatch: "
                    f"expected {expected_digest}, got {actual_digest}"
                )
        self._model = _load_yolo_model(self._config)
        return self._model

    def _convert_result(
        self, result: Any, frame: RGBFrame | RGBDFrame
    ) -> tuple[Detection2D, ...]:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return ()

        xyxy = _as_numpy(boxes.xyxy)
        confidences = _as_numpy(boxes.conf).reshape(-1)
        class_ids = _as_numpy(boxes.cls).reshape(-1)
        if xyxy.ndim != 2 or xyxy.shape[1] != 4:
            raise ValueError(f"YOLO boxes must have shape (N, 4), got {xyxy.shape}")
        detection_count = xyxy.shape[0]
        if confidences.shape != (detection_count,) or class_ids.shape != (
            detection_count,
        ):
            raise ValueError("YOLO box, confidence, and class counts must match")
        if detection_count == 0:
            return ()

        masks = getattr(result, "masks", None)
        if masks is None:
            raise RuntimeError("segmentation model returned boxes without instance masks")
        mask_data = _as_numpy(masks.data)
        height, width = frame.rgb.shape[:2]
        expected_mask_shape = (detection_count, height, width)
        if mask_data.shape != expected_mask_shape:
            raise ValueError(
                f"YOLO masks must have shape {expected_mask_shape}, got {mask_data.shape}"
            )

        names = getattr(result, "names", None)
        if not isinstance(names, Mapping):
            raise ValueError("YOLO result must provide a class-name mapping")

        detections: list[Detection2D] = []
        for index in range(detection_count):
            confidence = float(confidences[index])
            if not np.isfinite(confidence) or confidence < self._config.confidence_threshold:
                continue

            raw_class_id = float(class_ids[index])
            if not np.isfinite(raw_class_id) or not raw_class_id.is_integer():
                raise ValueError(f"YOLO class ID must be an integer, got {raw_class_id}")
            class_id = int(raw_class_id)
            if class_id not in names:
                raise ValueError(f"YOLO class-name mapping has no ID {class_id}")
            class_name = str(names[class_id])
            if (
                self._target_class_names is not None
                and class_name.lower() not in self._target_class_names
            ):
                continue

            coordinates = np.asarray(xyxy[index], dtype=np.float64)
            if not np.all(np.isfinite(coordinates)):
                raise ValueError("YOLO bounding boxes must contain only finite values")
            x1 = float(np.clip(coordinates[0], 0.0, width))
            y1 = float(np.clip(coordinates[1], 0.0, height))
            x2 = float(np.clip(coordinates[2], 0.0, width))
            y2 = float(np.clip(coordinates[3], 0.0, height))
            if x2 <= x1 or y2 <= y1:
                continue

            mask = np.asarray(
                mask_data[index] >= self._config.mask_threshold, dtype=np.bool_
            )
            detections.append(
                Detection2D(
                    class_id=class_id,
                    class_name=class_name,
                    confidence=confidence,
                    bbox_xyxy=(x1, y1, x2, y2),
                    mask=mask.copy(),
                )
            )
        return tuple(detections)
