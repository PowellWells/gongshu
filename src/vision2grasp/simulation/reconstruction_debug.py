"""Opt-in, read-only visual evidence for object reconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import cv2
import numpy as np

from vision2grasp.spatial_perception import SpatialObservation
from vision2grasp.target_perception import TargetSceneSnapshot

from .appearance import ProxyGeometry
from .object_reconstruction import ObjectReconstruction


RECONSTRUCTION_DEBUG_SCHEMA_VERSION: Final = "gongshu.reconstruction-debug/v1"


@dataclass(frozen=True, slots=True)
class ReconstructionDebugBundle:
    metadata: dict[str, Any]
    frames: dict[str, bytes]

    def frame(self, kind: str) -> bytes | None:
        value = self.frames.get(kind)
        return None if value is None else bytes(value)


def build_reconstruction_debug_bundle(
    snapshot: TargetSceneSnapshot,
    observation: SpatialObservation,
    reconstruction: ObjectReconstruction,
) -> ReconstructionDebugBundle:
    """Render the first four immutable stages; MuJoCo is supplied live."""

    frames = {
        "input": _encode_rgb(snapshot.frame.rgb),
        "mask": _render_mask(snapshot),
        "point-cloud": _render_point_cloud(observation, reconstruction),
        "proxy": _render_proxy(reconstruction),
    }
    return ReconstructionDebugBundle(
        metadata={
            "schema_version": RECONSTRUCTION_DEBUG_SCHEMA_VERSION,
            "enabled": True,
            "snapshot_id": snapshot.snapshot_id,
            "geometry_chain_id": observation.geometry_chain_id,
            "source_frame_id": observation.source_frame_id,
            "target_instance_id": observation.target_instance_id,
            "views": ["input", "mask", "point-cloud", "proxy", "mujoco"],
            "object_reconstruction": reconstruction.public_metadata(),
            "proxy_view_contract": "EXACT_OBJECT_RECONSTRUCTION_PROXY_SPEC",
        },
        frames=frames,
    )


def _encode_rgb(rgb: np.ndarray) -> bytes:
    image = cv2.cvtColor(np.asarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2BGR)
    return _encode_bgr(image)


def _render_mask(snapshot: TargetSceneSnapshot) -> bytes:
    rgb = np.asarray(snapshot.frame.rgb, dtype=np.uint8)
    mask = np.asarray(snapshot.target.mask, dtype=np.bool_)
    image = (rgb.astype(np.float32) * 0.22).astype(np.uint8)
    image[mask] = (
        rgb[mask].astype(np.float32) * 0.58 + np.array([0.0, 92.0, 104.0])
    ).clip(0, 255).astype(np.uint8)
    contours, _ = cv2.findContours(
        np.ascontiguousarray(mask.astype(np.uint8)),
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    cv2.drawContours(bgr, contours, -1, (0, 235, 255), 2)
    _label(bgr, "Segmentation Mask | same geometry_chain_id")
    return _encode_bgr(bgr)


def _render_point_cloud(
    observation: SpatialObservation,
    reconstruction: ObjectReconstruction,
) -> bytes:
    canvas = np.full((540, 760, 3), (22, 27, 36), dtype=np.uint8)
    points = np.asarray(observation.target_point_cloud, dtype=np.float64)
    if points.shape[0] > 12000:
        step = max(1, points.shape[0] // 12000)
        points = points[::step]
    x = points[:, 0]
    y = -points[:, 1]
    z = points[:, 2]
    x_min, x_max = np.quantile(x, [0.01, 0.99])
    y_min, y_max = np.quantile(y, [0.01, 0.99])
    px = 55 + (x - x_min) / max(x_max - x_min, 1e-9) * 650
    py = 480 - (y - y_min) / max(y_max - y_min, 1e-9) * 410
    depth = (z - np.min(z)) / max(float(np.ptp(z)), 1e-9)
    for index in range(points.shape[0]):
        color = (int(245 - 145 * depth[index]), int(100 + 120 * depth[index]), 245)
        cv2.circle(canvas, (int(px[index]), int(py[index])), 1, color, -1, cv2.LINE_AA)
    _label(canvas, f"Point Cloud | {reconstruction.point_count} inlier points")
    cv2.putText(
        canvas,
        "OpenCV camera projection: X right, -Y up; color = depth",
        (24, 520),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (180, 190, 205),
        1,
        cv2.LINE_AA,
    )
    return _encode_bgr(canvas)


def _render_proxy(reconstruction: ObjectReconstruction) -> bytes:
    canvas = np.full((540, 760, 3), (20, 25, 34), dtype=np.uint8)
    extents = reconstruction.proxy_extents_world_xyz
    width, depth, height = (float(value) for value in extents)
    scale = min(330.0 / max(width, depth, 1e-9), 360.0 / max(height, 1e-9))
    center = (300, 300)
    half_width = max(6, int(width * scale / 2.0))
    half_height = max(6, int(height * scale / 2.0))
    color = (255, 194, 48)
    geometry = reconstruction.proxy_geometry
    if geometry is ProxyGeometry.BOX:
        cv2.rectangle(
            canvas,
            (center[0] - half_width, center[1] - half_height),
            (center[0] + half_width, center[1] + half_height),
            color,
            3,
        )
    elif geometry is ProxyGeometry.CYLINDER:
        cap = max(5, int(min(half_width * 0.34, 24)))
        cv2.rectangle(
            canvas,
            (center[0] - half_width, center[1] - half_height + cap),
            (center[0] + half_width, center[1] + half_height - cap),
            color,
            3,
        )
        cv2.ellipse(canvas, (center[0], center[1] - half_height + cap), (half_width, cap), 0, 0, 360, color, 3)
        cv2.ellipse(canvas, (center[0], center[1] + half_height - cap), (half_width, cap), 0, 0, 360, color, 3)
    elif geometry is ProxyGeometry.CAPSULE:
        radius = min(half_width, half_height)
        cv2.rectangle(canvas, (center[0] - half_width + radius, center[1] - radius), (center[0] + half_width - radius, center[1] + radius), color, 3)
        cv2.circle(canvas, (center[0] - half_width + radius, center[1]), radius, color, 3)
        cv2.circle(canvas, (center[0] + half_width - radius, center[1]), radius, color, 3)
    else:
        cv2.ellipse(canvas, center, (half_width, half_height), 0, 0, 360, color, 3)
    top_center = (590, 300)
    top_half = (
        max(6, int(width * scale * 0.28)),
        max(6, int(depth * scale * 0.28)),
    )
    yaw_deg = float(np.degrees(reconstruction.target_yaw_world_rad))
    if geometry is ProxyGeometry.BOX:
        polygon = cv2.boxPoints(
            (top_center, (float(top_half[0] * 2), float(top_half[1] * 2)), yaw_deg)
        ).round().astype(np.int32)
        cv2.polylines(canvas, [polygon], True, (94, 224, 178), 3, cv2.LINE_AA)
    else:
        cv2.ellipse(
            canvas,
            top_center,
            top_half,
            yaw_deg,
            0,
            360,
            (94, 224, 178),
            3,
        )
    _label(canvas, "Generated Proxy | exact MuJoCo collision specification")
    cv2.putText(canvas, f"type: {geometry.value}", (28, 465), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (225, 230, 238), 2, cv2.LINE_AA)
    cv2.putText(canvas, f"extents XYZ: {width:.4f}, {depth:.4f}, {height:.4f} m", (28, 495), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (185, 195, 210), 1, cv2.LINE_AA)
    cv2.putText(canvas, f"object yaw: {np.degrees(reconstruction.target_yaw_world_rad):.1f} deg", (28, 523), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (185, 195, 210), 1, cv2.LINE_AA)
    return _encode_bgr(canvas)


def _label(image: np.ndarray, text: str) -> None:
    cv2.rectangle(image, (0, 0), (image.shape[1], 42), (9, 13, 20), -1)
    cv2.putText(image, text, (18, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (242, 246, 252), 2, cv2.LINE_AA)


def _encode_bgr(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 91])
    if not ok:
        raise RuntimeError("failed to encode reconstruction debug frame")
    return encoded.tobytes()


__all__ = [
    "RECONSTRUCTION_DEBUG_SCHEMA_VERSION",
    "ReconstructionDebugBundle",
    "build_reconstruction_debug_bundle",
]
