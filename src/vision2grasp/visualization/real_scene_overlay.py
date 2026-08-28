"""Human-readable grasp overlays drawn directly on real RGB frames."""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import (
    Detection2D,
    PlanarGraspCandidate,
    PlanarLocalizedTarget,
    RGBFrame,
    TableCalibration,
)
from vision2grasp.geometry.table_calibration import table_to_image


def render_real_scene_overlay(
    frame: RGBFrame,
    *,
    calibration: TableCalibration | None,
    detection: Detection2D | None,
    target: PlanarLocalizedTarget | None,
    candidates: Sequence[PlanarGraspCandidate],
) -> NDArray[np.uint8]:
    """Draw measured table coordinates and estimated top-grasp geometry."""

    image = frame.rgb.copy()
    if calibration is not None:
        _draw_table_axes(image, calibration)
    if detection is not None:
        _draw_detection(image, detection)
    if target is not None:
        center = tuple(np.rint(target.center_image_px).astype(int))
        cv2.drawMarker(
            image,
            center,
            (255, 255, 255),
            markerType=cv2.MARKER_CROSS,
            markerSize=18,
            thickness=2,
            line_type=cv2.LINE_AA,
        )
        text = (
            f"MEASURED XY {target.center_table_m[0] * 1000:.0f},"
            f"{target.center_table_m[1] * 1000:.0f} mm"
        )
        cv2.putText(
            image,
            text,
            (max(8, center[0] + 10), max(22, center[1] - 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    if calibration is not None and candidates:
        _draw_gripper(image, calibration, candidates[0])
    return image


def _draw_detection(image: NDArray[np.uint8], detection: Detection2D) -> None:
    if detection.mask.shape != image.shape[:2]:
        raise ValueError("detection mask shape does not match RGB frame")
    overlay = image.copy()
    overlay[detection.mask] = np.array([0, 215, 255], dtype=np.uint8)
    cv2.addWeighted(overlay, 0.34, image, 0.66, 0.0, dst=image)
    x1, y1, x2, y2 = (int(round(value)) for value in detection.bbox_xyxy)
    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 215, 255), 2)
    cv2.putText(
        image,
        f"{detection.class_name} {detection.confidence:.3f}",
        (max(8, x1), max(22, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def _draw_table_axes(
    image: NDArray[np.uint8], calibration: TableCalibration
) -> None:
    polygon = np.rint(calibration.image_points_px).astype(np.int32)
    cv2.polylines(image, [polygon], True, (90, 170, 255), 2, cv2.LINE_AA)
    axis_length = min(0.10, calibration.table_width_m, calibration.table_height_m)
    axes_table = np.array(
        [[0.0, 0.0], [axis_length, 0.0], [0.0, axis_length]], dtype=np.float64
    )
    axes_image = np.rint(table_to_image(calibration, axes_table)).astype(int)
    origin = tuple(axes_image[0])
    cv2.arrowedLine(
        image, origin, tuple(axes_image[1]), (255, 90, 80), 3, cv2.LINE_AA, tipLength=0.16
    )
    cv2.arrowedLine(
        image, origin, tuple(axes_image[2]), (80, 255, 130), 3, cv2.LINE_AA, tipLength=0.16
    )
    cv2.putText(image, "TABLE ORIGIN", origin, cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 2, cv2.LINE_AA)


def _draw_gripper(
    image: NDArray[np.uint8],
    calibration: TableCalibration,
    candidate: PlanarGraspCandidate,
) -> None:
    center = candidate.center_table_m
    closing = np.array(
        [np.cos(candidate.yaw_rad), np.sin(candidate.yaw_rad)], dtype=np.float64
    )
    finger = np.array([-closing[1], closing[0]], dtype=np.float64)
    half_opening = candidate.estimated_gripper_width_m / 2.0
    half_finger_length = 0.035
    left_center = center - closing * half_opening
    right_center = center + closing * half_opening
    geometry_table = np.vstack(
        [
            center,
            left_center - finger * half_finger_length,
            left_center + finger * half_finger_length,
            right_center - finger * half_finger_length,
            right_center + finger * half_finger_length,
            center - closing * half_opening,
            center + closing * half_opening,
        ]
    )
    geometry_image = np.rint(table_to_image(calibration, geometry_table)).astype(int)
    center_px = tuple(geometry_image[0])
    cv2.line(image, tuple(geometry_image[1]), tuple(geometry_image[2]), (255, 70, 70), 5, cv2.LINE_AA)
    cv2.line(image, tuple(geometry_image[3]), tuple(geometry_image[4]), (255, 70, 70), 5, cv2.LINE_AA)
    cv2.line(image, tuple(geometry_image[5]), tuple(geometry_image[6]), (255, 210, 70), 2, cv2.LINE_AA)
    cv2.circle(image, center_px, 9, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.circle(image, center_px, 3, (255, 255, 255), -1, cv2.LINE_AA)
    cv2.putText(
        image,
        (
            f"EST YAW {np.degrees(candidate.yaw_rad):.1f} deg | "
            f"WIDTH {candidate.estimated_gripper_width_m * 1000:.1f} mm | "
            f"SCORE {candidate.final_score:.3f}"
        ),
        (12, image.shape[0] - 18),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


__all__ = ["render_real_scene_overlay"]
