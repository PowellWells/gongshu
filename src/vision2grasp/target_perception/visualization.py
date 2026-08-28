"""Low-interference overlays for selectable target instances."""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import RGBFrame

from .contracts import TargetInstance


_PALETTE = (
    (34, 180, 246),
    (29, 202, 164),
    (247, 165, 54),
    (172, 111, 240),
    (240, 103, 135),
    (95, 190, 95),
)


def render_target_overlay(
    frame: RGBFrame,
    instances: tuple[TargetInstance, ...],
    *,
    selected_target_id: str | None,
) -> NDArray[np.uint8]:
    """Render candidate masks without exposing model-specific diagnostics."""

    image = frame.rgb.copy()
    selected = selected_target_id is not None
    for index, instance in enumerate(instances):
        if instance.mask.shape != image.shape[:2]:
            raise ValueError("target mask shape does not match frozen RGB frame")
        is_selected = instance.instance_id == selected_target_id
        color = np.asarray(
            (21, 203, 177) if is_selected else (125, 145, 164) if selected else _PALETTE[index % len(_PALETTE)],
            dtype=np.float32,
        )
        alpha = 0.36 if is_selected else 0.07 if selected else 0.16
        pixels = image[instance.mask].astype(np.float32)
        image[instance.mask] = np.clip(pixels * (1.0 - alpha) + color * alpha, 0, 255).astype(np.uint8)

    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    for index, instance in enumerate(instances):
        is_selected = instance.instance_id == selected_target_id
        if selected and not is_selected:
            bgr_color = (145, 140, 135)
            thickness = 1
        else:
            rgb_color = (21, 203, 177) if is_selected else _PALETTE[index % len(_PALETTE)]
            bgr_color = (rgb_color[2], rgb_color[1], rgb_color[0])
            thickness = 3 if is_selected else 2
        contours, _ = cv2.findContours(
            instance.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(bgr, contours, -1, bgr_color, thickness, cv2.LINE_AA)
        x1, y1, x2, y2 = (int(round(value)) for value in instance.bbox_xyxy)
        cv2.rectangle(bgr, (x1, y1), (x2, y2), bgr_color, thickness, cv2.LINE_AA)
        label = "TARGET LOCKED" if is_selected else f"Candidate {index + 1:02d}"
        font_scale = max(0.42, min(frame.rgb.shape[:2]) / 900.0)
        (text_width, text_height), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1
        )
        label_y = max(text_height + 7, y1)
        cv2.rectangle(
            bgr,
            (x1, label_y - text_height - 7),
            (min(bgr.shape[1] - 1, x1 + text_width + 9), label_y + baseline + 2),
            bgr_color,
            -1,
        )
        cv2.putText(
            bgr,
            label,
            (x1 + 4, label_y - 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def encode_jpeg(rgb: NDArray[np.uint8], *, quality: int = 90) -> bytes:
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("JPEG source must be an HxWx3 uint8 RGB image")
    ok, encoded = cv2.imencode(
        ".jpg",
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    if not ok:
        raise RuntimeError("failed to encode target-perception JPEG")
    return encoded.tobytes()
