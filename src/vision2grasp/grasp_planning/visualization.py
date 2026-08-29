"""Render actual target geometry and the selected geometry grasp."""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import GraspPlan


def render_grasp_overlay(snapshot: TargetSceneSnapshot, plan: GraspPlan) -> NDArray[np.uint8]:
    image = snapshot.frame.rgb.copy()
    tint = np.zeros_like(image)
    tint[snapshot.target.mask] = (16, 201, 194)
    image = cv2.addWeighted(image, 0.82, tint, 0.34, 0.0)
    contours, _ = cv2.findContours(
        snapshot.target.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(image, contours, -1, (78, 244, 228), 3, cv2.LINE_AA)

    center = np.array(snapshot.target.centroid_2d, dtype=np.float64)
    direction = np.array(plan.closing_vector[:2], dtype=np.float64, copy=True)
    direction /= max(float(np.linalg.norm(direction)), 1e-9)
    perpendicular = np.array([-direction[1], direction[0]])
    x1, y1, x2, y2 = snapshot.target.bbox_xyxy
    scale = max(min(x2 - x1, y2 - y1) * 0.68, 36.0)
    jaw_half_span = scale * 0.55
    finger_half_length = scale * 0.42
    for sign in (-1.0, 1.0):
        jaw_center = center + direction * jaw_half_span * sign
        start = jaw_center - perpendicular * finger_half_length
        end = jaw_center + perpendicular * finger_half_length
        cv2.line(image, tuple(np.rint(start).astype(int)), tuple(np.rint(end).astype(int)), (255, 190, 46), 6, cv2.LINE_AA)
    cv2.line(
        image,
        tuple(np.rint(center - direction * jaw_half_span).astype(int)),
        tuple(np.rint(center + direction * jaw_half_span).astype(int)),
        (255, 220, 95),
        3,
        cv2.LINE_AA,
    )
    cv2.drawMarker(image, tuple(np.rint(center).astype(int)), (255, 255, 255), cv2.MARKER_CROSS, 30, 3, cv2.LINE_AA)

    inset_origin = (max(image.shape[1] - 220, 20), max(image.shape[0] - 150, 20))
    overlay = image.copy()
    cv2.rectangle(overlay, inset_origin, (image.shape[1] - 20, image.shape[0] - 20), (6, 20, 34), -1)
    image = cv2.addWeighted(overlay, 0.74, image, 0.26, 0.0)
    arrow_start = (inset_origin[0] + 44, inset_origin[1] + 88)
    arrow_end = (inset_origin[0] + 138, inset_origin[1] + 42)
    cv2.arrowedLine(image, arrow_start, arrow_end, (64, 220, 255), 4, cv2.LINE_AA, tipLength=0.18)
    cv2.putText(image, "APPROACH +Z", (inset_origin[0] + 18, inset_origin[1] + 122), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (210, 236, 248), 1, cv2.LINE_AA)
    cv2.putText(image, "BEST GRASP", (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (255, 226, 108), 2, cv2.LINE_AA)
    return image


def encode_jpeg(image_rgb: NDArray[np.uint8], *, quality: int = 92) -> bytes:
    ok, encoded = cv2.imencode(
        ".jpg", cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality]
    )
    if not ok:
        raise RuntimeError("could not encode grasp visualization")
    return encoded.tobytes()
