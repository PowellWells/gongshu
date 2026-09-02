"""Session-only real-appearance extraction for stable MuJoCo proxies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
from typing import Any, Final

import cv2
import numpy as np
from numpy.typing import NDArray

from vision2grasp.target_perception import TargetSceneSnapshot


TARGET_APPEARANCE_SCHEMA_VERSION: Final = "gongshu.target-appearance/v1"
TARGET_TEXTURE_ASSET_NAME: Final = "target_appearance.png"


class ProxyGeometry(str, Enum):
    """Low-complexity proxy shapes shared by physics and visual shells."""

    BOX = "box"
    CYLINDER = "cylinder"
    CAPSULE = "capsule"
    ELLIPSOID = "ellipsoid"


@dataclass(frozen=True, slots=True)
class TargetAppearance:
    """Masked target appearance and low-complexity proxy classification.

    ``texture_png`` is deliberately kept as bytes. It is passed to MuJoCo's
    in-memory VFS and is not written to a runtime or repository directory.
    The texture is rendering-only; physics uses a separate untextured geom of
    the classified proxy shape.
    """

    snapshot_id: str
    source_frame_id: int
    target_instance_id: str
    semantic_label: str
    proxy_geometry: ProxyGeometry
    source_crop_xyxy: tuple[int, int, int, int]
    texture_size: tuple[int, int]
    foreground_pixel_count: int
    mean_rgb: tuple[int, int, int]
    mask_bbox_fill_ratio: float
    mask_circularity: float
    mask_elongation: float
    texture_png: bytes = field(repr=False)
    extraction_source: str = "LOCKED_SCENE_SNAPSHOT_RGB_PLUS_TARGET_MASK"

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip() or not self.target_instance_id.strip():
            raise ValueError("appearance snapshot and target identifiers must not be empty")
        if self.source_frame_id < 0 or self.foreground_pixel_count < 1:
            raise ValueError("appearance frame and foreground count must be valid")
        if not isinstance(self.proxy_geometry, ProxyGeometry):
            object.__setattr__(self, "proxy_geometry", ProxyGeometry(self.proxy_geometry))
        x1, y1, x2, y2 = self.source_crop_xyxy
        if x2 <= x1 or y2 <= y1:
            raise ValueError("appearance source crop must have positive area")
        width, height = self.texture_size
        if width < 1 or height < 1 or not self.texture_png:
            raise ValueError("appearance texture must be non-empty")
        if any(value < 0 or value > 255 for value in self.mean_rgb):
            raise ValueError("mean_rgb must contain uint8-compatible values")
        for value in (
            self.mask_bbox_fill_ratio,
            self.mask_circularity,
            self.mask_elongation,
        ):
            if not np.isfinite(value) or value < 0.0:
                raise ValueError("appearance shape metrics must be finite and non-negative")
        object.__setattr__(self, "texture_png", bytes(self.texture_png))

    @property
    def texture_sha256(self) -> str:
        return hashlib.sha256(self.texture_png).hexdigest()

    def model_assets(self) -> dict[str, bytes]:
        return {TARGET_TEXTURE_ASSET_NAME: bytes(self.texture_png)}

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": TARGET_APPEARANCE_SCHEMA_VERSION,
            "source": self.extraction_source,
            "snapshot_id": self.snapshot_id,
            "source_frame_id": self.source_frame_id,
            "target_instance_id": self.target_instance_id,
            "semantic_label": self.semantic_label,
            "proxy_geometry": self.proxy_geometry.value,
            "physics_geometry": f"STABLE_{self.proxy_geometry.value.upper()}_COLLISION_PROXY",
            "appearance_geometry": f"COLLISION_DISABLED_{self.proxy_geometry.value.upper()}",
            "source_crop_xyxy": list(self.source_crop_xyxy),
            "texture_size": {"width": self.texture_size[0], "height": self.texture_size[1]},
            "foreground_pixel_count": self.foreground_pixel_count,
            "mean_rgb": list(self.mean_rgb),
            "mask_bbox_fill_ratio": self.mask_bbox_fill_ratio,
            "mask_circularity": self.mask_circularity,
            "mask_elongation": self.mask_elongation,
            "background_removed": True,
            "storage": "SESSION_MEMORY",
            "texture_sha256": self.texture_sha256,
        }


def extract_target_appearance(
    snapshot: TargetSceneSnapshot,
    *,
    texture_side: int = 256,
) -> TargetAppearance:
    """Extract a clean target texture from the immutable RGB+mask snapshot."""

    if texture_side < 32 or texture_side > 1024:
        raise ValueError("texture_side must be between 32 and 1024")
    rgb = np.asarray(snapshot.frame.rgb, dtype=np.uint8)
    mask = np.asarray(snapshot.target.mask, dtype=np.bool_)
    if rgb.shape[:2] != mask.shape:
        raise ValueError("target appearance RGB and mask coordinates must match")
    rows, columns = np.nonzero(mask)
    if rows.size == 0:
        raise ValueError("target appearance mask is empty")
    x1, x2 = int(columns.min()), int(columns.max()) + 1
    y1, y2 = int(rows.min()), int(rows.max()) + 1
    crop = np.ascontiguousarray(rgb[y1:y2, x1:x2].copy())
    crop_mask = np.ascontiguousarray(mask[y1:y2, x1:x2])
    foreground = crop[crop_mask]
    median_rgb = np.median(foreground, axis=0).round().astype(np.uint8)

    # Remove every scene-background pixel before mapping. Filling the unused
    # part of the rectangular crop with the target's own robust median avoids
    # wrapping phone background around the proxy while retaining real surface
    # colour and printed details wherever the target mask is true.
    clean = crop.copy()
    clean[~crop_mask] = median_rgb
    scale = min(texture_side / clean.shape[1], texture_side / clean.shape[0])
    resized_width = max(1, int(round(clean.shape[1] * scale)))
    resized_height = max(1, int(round(clean.shape[0] * scale)))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(clean, (resized_width, resized_height), interpolation=interpolation)
    texture = np.empty((texture_side, texture_side, 3), dtype=np.uint8)
    texture[...] = median_rgb
    offset_x = (texture_side - resized_width) // 2
    offset_y = (texture_side - resized_height) // 2
    texture[offset_y : offset_y + resized_height, offset_x : offset_x + resized_width] = resized
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(texture, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("failed to encode in-memory target appearance texture")

    fill_ratio, circularity, elongation, neck_ratio = _shape_metrics(crop_mask)
    proxy = _classify_proxy(
        snapshot.target.class_name or "",
        fill_ratio=fill_ratio,
        circularity=circularity,
        elongation=elongation,
        neck_ratio=neck_ratio,
    )
    mean_rgb = tuple(int(value) for value in np.mean(foreground, axis=0).round())
    return TargetAppearance(
        snapshot_id=snapshot.snapshot_id,
        source_frame_id=snapshot.frame.frame_id,
        target_instance_id=snapshot.target.instance_id,
        semantic_label=snapshot.target.class_name or "",
        proxy_geometry=proxy,
        source_crop_xyxy=(x1, y1, x2, y2),
        texture_size=(texture_side, texture_side),
        foreground_pixel_count=int(rows.size),
        mean_rgb=mean_rgb,
        mask_bbox_fill_ratio=fill_ratio,
        mask_circularity=circularity,
        mask_elongation=elongation,
        texture_png=encoded.tobytes(),
    )


def _shape_metrics(mask: NDArray[np.bool_]) -> tuple[float, float, float, float]:
    binary = np.ascontiguousarray(mask.astype(np.uint8))
    area = float(np.count_nonzero(binary))
    height, width = binary.shape
    fill_ratio = area / max(float(width * height), 1.0)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea)
    perimeter = float(cv2.arcLength(contour, True))
    circularity = 0.0 if perimeter <= 0.0 else float(4.0 * np.pi * area / (perimeter * perimeter))
    points = np.column_stack(np.nonzero(binary)[::-1]).astype(np.float64)
    if points.shape[0] < 3 or np.ptp(points[:, 0]) == 0.0 or np.ptp(points[:, 1]) == 0.0:
        elongation = 1.0
    else:
        covariance = np.cov(points, rowvar=False)
        eigenvalues = np.maximum(np.linalg.eigvalsh(covariance), 1e-9)
        elongation = float(np.sqrt(eigenvalues[-1] / eigenvalues[0]))
    row_widths = np.count_nonzero(binary, axis=1).astype(np.float64)
    top_end = max(1, height // 4)
    middle_start = max(0, height // 3)
    middle_end = max(middle_start + 1, 2 * height // 3)
    top_width = float(np.mean(row_widths[:top_end]))
    middle_width = float(np.mean(row_widths[middle_start:middle_end]))
    neck_ratio = top_width / max(middle_width, 1.0)
    return fill_ratio, circularity, elongation, neck_ratio


def _classify_proxy(
    semantic_label: str,
    *,
    fill_ratio: float,
    circularity: float,
    elongation: float,
    neck_ratio: float,
) -> ProxyGeometry:
    label = semantic_label.casefold()
    if any(token in label for token in ("box", "package", "parcel", "carton", "book", "盒", "箱", "包装")):
        return ProxyGeometry.BOX
    if any(token in label for token in ("bottle", "cup", "mug", "can", "jar", "瓶", "杯", "罐")):
        return ProxyGeometry.CYLINDER
    if any(token in label for token in ("banana", "elongated", "sausage", "handle", "香蕉", "长条")):
        return ProxyGeometry.CAPSULE
    if any(token in label for token in ("apple", "orange", "ball", "round", "苹果", "橙", "球")):
        return ProxyGeometry.ELLIPSOID
    if elongation >= 2.15:
        return ProxyGeometry.CAPSULE
    if neck_ratio <= 0.72 and elongation >= 1.35:
        return ProxyGeometry.CYLINDER
    if fill_ratio >= 0.84:
        return ProxyGeometry.BOX
    if circularity >= 0.72 and elongation <= 1.45:
        return ProxyGeometry.ELLIPSOID
    return ProxyGeometry.ELLIPSOID
