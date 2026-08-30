"""FastSAM adapter that emits model-neutral selectable target instances."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np

from vision2grasp.contracts import RGBFrame
from vision2grasp.model_assets import ModelAsset

from .contracts import TargetInstance
from .model_resolver import (
    FastSAMChecksumError,
    FastSAMModelLoadError,
    FastSAMModelLocation,
    FastSAMModelNotFoundError,
    FastSAMModelResolver,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_DIR = _PROJECT_ROOT / "artifacts" / "ultralytics" / "config"
_FASTSAM_S_SHA256 = "c9f78716a81c7aff0d608ccc73e1b82ab3aaad86005049f6a92106a0be6d0844"
FASTSAM_MODEL_ASSET = ModelAsset(
    key="fastsam-small",
    relative_path=Path("fastsam") / "FastSAM-s.pt",
    url="https://github.com/ultralytics/assets/releases/download/v8.4.0/FastSAM-s.pt",
    size_bytes=23_851_578,
    sha256=_FASTSAM_S_SHA256,
    source="https://github.com/ultralytics/assets/releases/tag/v8.4.0",
    revision="v8.4.0",
    license="AGPL-3.0",
)


@dataclass(frozen=True, slots=True)
class FastSAMTargetSegmenterConfig:
    """Deterministic CPU configuration for object-agnostic candidate masks."""

    weights_path: Path | None = None
    weights_sha256: str | None = _FASTSAM_S_SHA256
    confidence_threshold: float = 0.40
    mask_threshold: float = 0.50
    image_size: int = 640
    minimum_area_ratio: float = 0.003
    maximum_area_ratio: float = 0.80
    duplicate_iou_threshold: float = 0.82
    containment_threshold: float = 0.94
    maximum_candidates: int = 12
    device: str = "cpu"
    allow_download: bool = True
    ultralytics_config_dir: Path = _DEFAULT_CONFIG_DIR

    def __post_init__(self) -> None:
        if self.weights_path is not None:
            object.__setattr__(self, "weights_path", Path(self.weights_path))
        object.__setattr__(self, "ultralytics_config_dir", Path(self.ultralytics_config_dir))
        for name, value in (
            ("confidence_threshold", self.confidence_threshold),
            ("mask_threshold", self.mask_threshold),
            ("minimum_area_ratio", self.minimum_area_ratio),
            ("maximum_area_ratio", self.maximum_area_ratio),
            ("duplicate_iou_threshold", self.duplicate_iou_threshold),
            ("containment_threshold", self.containment_threshold),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1]")
        if self.minimum_area_ratio >= self.maximum_area_ratio:
            raise ValueError("minimum_area_ratio must be smaller than maximum_area_ratio")
        if self.image_size <= 0:
            raise ValueError("image_size must be positive")
        if self.maximum_candidates <= 0:
            raise ValueError("maximum_candidates must be positive")
        if self.device != "cpu":
            raise ValueError("Gongshu v0.4 target perception is frozen to device='cpu'")
        if self.weights_sha256 is not None:
            digest = self.weights_sha256.strip().lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("weights_sha256 must be a 64-character hexadecimal digest")
            object.__setattr__(self, "weights_sha256", digest)


class _FastSAMModel(Protocol):
    def predict(self, source: Any, **kwargs: Any) -> Sequence[Any]: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def _load_fastsam_model(
    config: FastSAMTargetSegmenterConfig,
    weights_path: Path,
) -> _FastSAMModel:
    config_dir = config.ultralytics_config_dir.resolve()
    config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(config_dir))
    from ultralytics import FastSAM
    from ultralytics.utils import SETTINGS

    SETTINGS.update({"sync": False})
    return cast(_FastSAMModel, FastSAM(str(weights_path)))


class FastSAMTargetSegmenter:
    """Generate generic target masks without requiring semantic class labels."""

    def __init__(
        self,
        config: FastSAMTargetSegmenterConfig | None = None,
        *,
        model: _FastSAMModel | None = None,
        model_resolver: FastSAMModelResolver | None = None,
    ) -> None:
        self._config = config or FastSAMTargetSegmenterConfig()
        self._model = model
        self._model_resolver = model_resolver or FastSAMModelResolver()
        self._model_path: Path | None = None
        self._model_location: FastSAMModelLocation | None = None

    @property
    def backend_name(self) -> str:
        return (
            self._config.weights_path.stem
            if self._config.weights_path is not None
            else Path(FASTSAM_MODEL_ASSET.relative_path).stem
        )

    @property
    def model_path(self) -> Path | None:
        return self._model_path

    @property
    def model_location(self) -> FastSAMModelLocation | None:
        return self._model_location

    def predict(self, frame: RGBFrame) -> tuple[TargetInstance, ...]:
        model = self._ensure_model()
        bgr = np.ascontiguousarray(frame.rgb[..., ::-1])
        results = model.predict(
            source=bgr,
            conf=self._config.confidence_threshold,
            iou=0.90,
            imgsz=self._config.image_size,
            device=self._config.device,
            retina_masks=True,
            verbose=False,
            save=False,
        )
        if len(results) != 1:
            raise RuntimeError(f"single-frame inference must return one result, got {len(results)}")
        return self._convert_result(results[0], frame)

    def _ensure_model(self) -> _FastSAMModel:
        if self._model is not None:
            return self._model
        weights_path = self._config.weights_path
        if weights_path is None:
            resolved = self._model_resolver.resolve(
                FASTSAM_MODEL_ASSET,
                allow_download=self._config.allow_download,
            )
            weights_path = resolved.path
            self._model_location = resolved.location
        if not weights_path.is_file():
            raise FastSAMModelNotFoundError(
                f"FastSAM-s checkpoint not found at {weights_path}"
            )
        if self._config.weights_sha256 is not None:
            actual_digest = _sha256(weights_path)
            if actual_digest != self._config.weights_sha256:
                raise FastSAMChecksumError(
                    "FastSAM-s checkpoint SHA-256 mismatch: "
                    f"expected {self._config.weights_sha256}, got {actual_digest}"
                )
        self._model_path = weights_path.resolve()
        try:
            self._model = _load_fastsam_model(self._config, weights_path)
        except Exception as error:
            raise FastSAMModelLoadError(
                f"FastSAM-s could not be loaded from {weights_path}: {error}"
            ) from error
        return self._model

    def _convert_result(self, result: Any, frame: RGBFrame) -> tuple[TargetInstance, ...]:
        boxes = getattr(result, "boxes", None)
        masks = getattr(result, "masks", None)
        if boxes is None or masks is None:
            return ()
        confidences = _as_numpy(boxes.conf).reshape(-1)
        mask_data = _as_numpy(masks.data)
        height, width = frame.rgb.shape[:2]
        if mask_data.ndim != 3 or mask_data.shape[1:] != (height, width):
            raise ValueError(
                "FastSAM masks must use original frame coordinates, got "
                f"{mask_data.shape} for {(height, width)}"
            )
        if confidences.shape != (mask_data.shape[0],):
            raise ValueError("FastSAM mask and confidence counts must match")

        frame_area = height * width
        proposals: list[tuple[float, int, np.ndarray]] = []
        for index, raw_mask in enumerate(mask_data):
            confidence = float(confidences[index])
            if not np.isfinite(confidence) or confidence < self._config.confidence_threshold:
                continue
            mask = np.asarray(raw_mask >= self._config.mask_threshold, dtype=np.bool_)
            area = int(np.count_nonzero(mask))
            area_ratio = area / frame_area
            if not self._config.minimum_area_ratio <= area_ratio <= self._config.maximum_area_ratio:
                continue
            proposals.append((confidence, area, mask))
        proposals.sort(key=lambda item: (-item[0], -item[1]))

        kept: list[tuple[float, int, np.ndarray]] = []
        for proposal in proposals:
            if any(self._is_duplicate(proposal, existing) for existing in kept):
                continue
            kept.append(proposal)
            if len(kept) >= self._config.maximum_candidates:
                break

        instances: list[TargetInstance] = []
        for rank, (confidence, _area, mask) in enumerate(kept, start=1):
            rows, columns = np.nonzero(mask)
            x1 = float(columns.min())
            y1 = float(rows.min())
            x2 = float(columns.max() + 1)
            y2 = float(rows.max() + 1)
            instances.append(
                TargetInstance(
                    instance_id=f"target-{frame.frame_id}-{rank:02d}",
                    mask=mask.copy(),
                    bbox_xyxy=(x1, y1, x2, y2),
                    centroid_2d=(float(columns.mean()), float(rows.mean())),
                    source_frame_id=frame.frame_id,
                    source_timestamp_s=frame.timestamp_s,
                    confidence=confidence,
                    class_name=None,
                    semantic_source=None,
                )
            )
        return tuple(instances)

    def _is_duplicate(
        self,
        candidate: tuple[float, int, np.ndarray],
        existing: tuple[float, int, np.ndarray],
    ) -> bool:
        _confidence_a, area_a, mask_a = candidate
        _confidence_b, area_b, mask_b = existing
        intersection = int(np.count_nonzero(mask_a & mask_b))
        if intersection == 0:
            return False
        union = area_a + area_b - intersection
        iou = intersection / union
        containment = intersection / min(area_a, area_b)
        return (
            iou >= self._config.duplicate_iou_threshold
            or containment >= self._config.containment_threshold
        )
