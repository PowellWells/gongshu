"""Honest depth-map and target point-cloud rendering for the Workspace."""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import SpatialObservation


def render_spatial_overview(
    observation: SpatialObservation,
    snapshot: TargetSceneSnapshot,
) -> NDArray[np.uint8]:
    """Render actual depth output and actual mask-backprojected points side by side."""

    height, width = 720, 1280
    canvas = np.full((height, width, 3), (10, 24, 38), dtype=np.uint8)
    left = _render_depth(observation, snapshot)
    right = _render_point_cloud(observation)
    canvas[:, :640] = left
    canvas[:, 640:] = right
    cv2.line(canvas, (639, 0), (639, height), (70, 105, 132), 1, cv2.LINE_AA)
    return canvas


def encode_jpeg(image_rgb: NDArray[np.uint8], *, quality: int = 92) -> bytes:
    success, encoded = cv2.imencode(
        ".jpg",
        cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    if not success:
        raise RuntimeError("could not encode spatial visualization")
    return encoded.tobytes()


def _render_depth(
    observation: SpatialObservation,
    snapshot: TargetSceneSnapshot,
) -> NDArray[np.uint8]:
    depth = observation.depth_frame.values
    valid = np.isfinite(depth) & (depth > 0.0)
    if not np.any(valid):
        raise ValueError("depth visualization has no valid pixels")
    lower, upper = np.percentile(depth[valid], [2.0, 98.0])
    if not np.isfinite(lower) or not np.isfinite(upper):
        raise ValueError("depth visualization range is invalid")
    if upper <= lower:
        upper = lower + max(abs(lower) * 1e-3, 1e-6)
    normalized = np.zeros(depth.shape, dtype=np.uint8)
    normalized[valid] = np.clip(
        (depth[valid] - lower) / (upper - lower) * 255.0,
        0.0,
        255.0,
    ).astype(np.uint8)
    color_bgr = cv2.applyColorMap(255 - normalized, cv2.COLORMAP_TURBO)
    color_bgr[~valid] = (8, 16, 24)
    color = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)
    contours, _ = cv2.findContours(
        snapshot.target.mask.astype(np.uint8),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    cv2.drawContours(color, contours, -1, (86, 239, 232), 3, cv2.LINE_AA)
    panel = _contain_on_panel(color)
    return panel


def _render_point_cloud(observation: SpatialObservation) -> NDArray[np.uint8]:
    panel = np.full((720, 640, 3), (9, 22, 35), dtype=np.uint8)
    points = observation.target_point_cloud.astype(np.float64)
    center = observation.centroid_xyz.astype(np.float64)
    centered = points - center
    yaw = np.deg2rad(32.0)
    pitch = np.deg2rad(-24.0)
    rotate_y = np.array(
        [[np.cos(yaw), 0.0, np.sin(yaw)], [0.0, 1.0, 0.0], [-np.sin(yaw), 0.0, np.cos(yaw)]]
    )
    rotate_x = np.array(
        [[1.0, 0.0, 0.0], [0.0, np.cos(pitch), -np.sin(pitch)], [0.0, np.sin(pitch), np.cos(pitch)]]
    )
    rotated = centered @ (rotate_y @ rotate_x).T
    planar = rotated[:, :2]
    radius = float(np.percentile(np.linalg.norm(planar, axis=1), 98.0))
    if not np.isfinite(radius) or radius <= 1e-9:
        radius = 1.0
    scale = 230.0 / radius
    pixels = np.rint(planar * scale + np.array([320.0, 378.0])).astype(np.int32)
    z_values = points[:, 2]
    z_min, z_max = float(np.min(z_values)), float(np.max(z_values))
    z_span = max(z_max - z_min, 1e-9)
    colors = np.clip((z_values - z_min) / z_span * 255.0, 0.0, 255.0).astype(np.uint8)
    palette = cv2.cvtColor(
        cv2.applyColorMap(colors.reshape(-1, 1), cv2.COLORMAP_TURBO),
        cv2.COLOR_BGR2RGB,
    ).reshape(-1, 3)
    for (x, y), color in zip(pixels, palette, strict=True):
        if 20 <= x < 620 and 85 <= y < 665:
            cv2.circle(panel, (int(x), int(y)), 2, tuple(int(v) for v in color), -1, cv2.LINE_AA)
    cv2.drawMarker(panel, (320, 378), (255, 255, 255), cv2.MARKER_CROSS, 22, 2, cv2.LINE_AA)
    return panel


def _contain_on_panel(image: NDArray[np.uint8]) -> NDArray[np.uint8]:
    panel = np.full((720, 640, 3), (9, 22, 35), dtype=np.uint8)
    available_width, available_height = 600, 560
    scale = min(available_width / image.shape[1], available_height / image.shape[0])
    resized = cv2.resize(
        image,
        (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale))),
        interpolation=cv2.INTER_LINEAR,
    )
    x = (640 - resized.shape[1]) // 2
    y = 80 + (560 - resized.shape[0]) // 2
    panel[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return panel
