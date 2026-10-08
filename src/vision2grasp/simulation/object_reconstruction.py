"""Point-cloud-first object reconstruction for MuJoCo validation proxies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from vision2grasp.spatial_perception import DepthMode, SpatialObservation
from vision2grasp.target_perception import TargetSceneSnapshot

from .appearance import ProxyGeometry, TargetAppearance


OBJECT_RECONSTRUCTION_SCHEMA_VERSION: Final = "gongshu.object-reconstruction/v1"
_CAMERA_DELTA_TO_WORLD: Final = np.array(
    [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]],
    dtype=np.float64,
)


@dataclass(frozen=True, slots=True)
class ObjectReconstruction:
    """Frozen object geometry derived independently of the selected grasp."""

    snapshot_id: str
    geometry_chain_id: str
    source_frame_id: int
    target_instance_id: str
    centroid_camera_xyz: NDArray[np.float64]
    principal_axes_camera: NDArray[np.float64]
    robust_extents_camera_xyz: NDArray[np.float64]
    proxy_geometry: ProxyGeometry
    proxy_extents_world_xyz: NDArray[np.float64]
    target_yaw_world_rad: float
    confidence: float
    point_count: int
    depth_mode: str
    source: str = "TARGET_POINT_CLOUD_ROBUST_OBB"
    fallback_reason: str | None = None
    inferred_hidden_extent: bool = False

    def __post_init__(self) -> None:
        for value, name in (
            (self.snapshot_id, "snapshot_id"),
            (self.geometry_chain_id, "geometry_chain_id"),
            (self.target_instance_id, "target_instance_id"),
        ):
            if not str(value).strip():
                raise ValueError(f"{name} must not be empty")
        if self.source_frame_id < 0 or self.point_count < 1:
            raise ValueError("reconstruction frame and point count must be valid")
        if not isinstance(self.proxy_geometry, ProxyGeometry):
            object.__setattr__(self, "proxy_geometry", ProxyGeometry(self.proxy_geometry))
        if not np.isfinite(self.target_yaw_world_rad):
            raise ValueError("target yaw must be finite")
        if not np.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("reconstruction confidence must be in [0, 1]")
        for name in (
            "centroid_camera_xyz",
            "robust_extents_camera_xyz",
            "proxy_extents_world_xyz",
        ):
            value = np.asarray(getattr(self, name), dtype=np.float64)
            if value.shape != (3,) or not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must be a finite 3-vector")
            if name != "centroid_camera_xyz" and np.any(value <= 0.0):
                raise ValueError(f"{name} must be positive")
            immutable = np.ascontiguousarray(value.copy())
            immutable.setflags(write=False)
            object.__setattr__(self, name, immutable)
        axes = np.asarray(self.principal_axes_camera, dtype=np.float64)
        if axes.shape != (3, 3) or not np.all(np.isfinite(axes)):
            raise ValueError("principal_axes_camera must be a finite 3x3 matrix")
        immutable_axes = np.ascontiguousarray(axes.copy())
        immutable_axes.setflags(write=False)
        object.__setattr__(self, "principal_axes_camera", immutable_axes)

    @property
    def is_point_cloud_driven(self) -> bool:
        return self.fallback_reason is None

    def camera_delta_to_world(self, delta_camera_xyz: NDArray[np.float64]) -> NDArray[np.float64]:
        delta = np.asarray(delta_camera_xyz, dtype=np.float64)
        if delta.shape != (3,) or not np.all(np.isfinite(delta)):
            raise ValueError("camera delta must be a finite 3-vector")
        return _CAMERA_DELTA_TO_WORLD @ delta

    def public_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": OBJECT_RECONSTRUCTION_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "geometry_chain_id": self.geometry_chain_id,
            "source_frame_id": self.source_frame_id,
            "target_instance_id": self.target_instance_id,
            "source": self.source,
            "point_count": self.point_count,
            "depth_mode": self.depth_mode,
            "centroid_camera_xyz": self.centroid_camera_xyz.tolist(),
            "principal_axes_camera": self.principal_axes_camera.tolist(),
            "robust_extents_camera_xyz": self.robust_extents_camera_xyz.tolist(),
            "proxy_geometry": self.proxy_geometry.value,
            "proxy_extents_world_xyz": self.proxy_extents_world_xyz.tolist(),
            "target_yaw_world_rad": self.target_yaw_world_rad,
            "target_yaw_world_deg": float(np.degrees(self.target_yaw_world_rad)),
            "confidence": self.confidence,
            "fallback_reason": self.fallback_reason,
            "inferred_hidden_extent": self.inferred_hidden_extent,
            "camera_to_world_axis_mapping": {
                "world_x": "+camera_x",
                "world_y": "+camera_z",
                "world_z": "-camera_y",
            },
            "grasp_independent": True,
        }


def reconstruct_object(
    observation: SpatialObservation,
    snapshot: TargetSceneSnapshot,
    appearance: TargetAppearance | None = None,
) -> ObjectReconstruction:
    """Build a robust low-complexity proxy from the selected target cloud."""

    _validate_chain(observation, snapshot)
    points = np.asarray(observation.target_point_cloud, dtype=np.float64)
    lower = np.quantile(points, 0.02, axis=0)
    upper = np.quantile(points, 0.98, axis=0)
    inliers = points[np.all((points >= lower) & (points <= upper), axis=1)]
    if inliers.shape[0] < max(16, min(64, points.shape[0] // 4)):
        inliers = points
    centroid = np.median(inliers, axis=0)
    centered_camera = inliers - centroid
    covariance = np.cov(centered_camera, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    axes_camera = eigenvectors[:, order].T
    robust_camera_extents = _robust_extent(centered_camera)

    world_points = centered_camera @ _CAMERA_DELTA_TO_WORLD.T
    horizontal = world_points[:, :2]
    horizontal_covariance = np.cov(horizontal, rowvar=False)
    horizontal_values, horizontal_vectors = np.linalg.eigh(horizontal_covariance)
    major = horizontal_vectors[:, int(np.argmax(horizontal_values))]
    if major[0] < 0.0:
        major = -major
    yaw = float(np.arctan2(major[1], major[0]))
    cos_yaw, sin_yaw = np.cos(yaw), np.sin(yaw)
    world_to_object_xy = np.array(
        [[cos_yaw, sin_yaw], [-sin_yaw, cos_yaw]], dtype=np.float64
    )
    object_xy = horizontal @ world_to_object_xy.T
    raw_world_extents = np.array(
        [*_robust_extent(object_xy), _robust_extent(world_points[:, 2:3])[0]],
        dtype=np.float64,
    )
    raw_world_extents[:2] = np.sort(raw_world_extents[:2])[::-1]
    scaled_extents = _normalize_extents(raw_world_extents, observation.depth_mode)

    visible_width = max(float(scaled_extents[0]), 0.015)
    visible_height = max(float(scaled_extents[2]), 0.02)
    observed_hidden = float(scaled_extents[1])
    completed_hidden = max(observed_hidden, min(visible_width, visible_height) * 0.38)
    completed_hidden = min(completed_hidden, visible_width)
    inferred_hidden = completed_hidden > observed_hidden * 1.05
    proxy_extents = np.array(
        [visible_width, completed_hidden, visible_height], dtype=np.float64
    )
    geometry = _classify_geometry(
        proxy_extents,
        raw_world_extents=raw_world_extents,
        observed_hidden_extent=observed_hidden,
        appearance=appearance,
    )
    if geometry is ProxyGeometry.CYLINDER:
        # MuJoCo's cylinder is rotationally symmetric. Keep the XML primitive
        # dimensions identical to the published proxy specification.
        proxy_extents[1] = proxy_extents[0]
    elif geometry is ProxyGeometry.CAPSULE:
        long_axis = int(np.argmax(proxy_extents))
        cross_axes = [index for index in range(3) if index != long_axis]
        cross_extent = min(float(proxy_extents[index]) for index in cross_axes)
        proxy_extents[cross_axes] = cross_extent
    support = min(1.0, np.log10(max(inliers.shape[0], 10)) / 3.0)
    depth_support = min(1.0, observed_hidden / max(visible_width, 1e-9))
    confidence = float(np.clip(0.55 * support + 0.30 * depth_support + 0.15, 0.0, 1.0))
    return ObjectReconstruction(
        snapshot_id=snapshot.snapshot_id,
        geometry_chain_id=observation.geometry_chain_id,
        source_frame_id=observation.source_frame_id,
        target_instance_id=observation.target_instance_id,
        centroid_camera_xyz=centroid,
        principal_axes_camera=axes_camera,
        robust_extents_camera_xyz=np.maximum(robust_camera_extents, 1e-6),
        proxy_geometry=geometry,
        proxy_extents_world_xyz=proxy_extents,
        target_yaw_world_rad=yaw,
        confidence=confidence,
        point_count=int(inliers.shape[0]),
        depth_mode=observation.depth_mode.value,
        inferred_hidden_extent=inferred_hidden,
    )


def fallback_reconstruction(
    *,
    snapshot_id: str,
    geometry_chain_id: str,
    source_frame_id: int,
    target_instance_id: str,
    centroid_camera_xyz: NDArray[np.float64],
    extents_xyz: NDArray[np.float64],
    appearance: TargetAppearance | None,
    reason: str,
) -> ObjectReconstruction:
    """Explicit compatibility fallback for callers without a SpatialObservation."""

    extents = np.clip(np.asarray(extents_xyz, dtype=np.float64), 0.015, 0.28)
    geometry = ProxyGeometry.BOX if appearance is None else appearance.proxy_geometry
    return ObjectReconstruction(
        snapshot_id=snapshot_id,
        geometry_chain_id=geometry_chain_id,
        source_frame_id=source_frame_id,
        target_instance_id=target_instance_id,
        centroid_camera_xyz=np.asarray(centroid_camera_xyz, dtype=np.float64),
        principal_axes_camera=np.eye(3, dtype=np.float64),
        robust_extents_camera_xyz=extents,
        proxy_geometry=geometry,
        proxy_extents_world_xyz=extents,
        target_yaw_world_rad=0.0,
        confidence=0.0,
        point_count=1,
        depth_mode="UNKNOWN",
        source="EXPLICIT_COMPATIBILITY_FALLBACK",
        fallback_reason=reason,
    )


def _validate_chain(
    observation: SpatialObservation, snapshot: TargetSceneSnapshot
) -> None:
    if observation.snapshot_id != snapshot.snapshot_id:
        raise ValueError("Object Reconstruction snapshot does not match SpatialObservation")
    if observation.geometry_chain_id != snapshot.geometry_chain_id:
        raise ValueError("Object Reconstruction geometry chain does not match snapshot")
    if observation.source_frame_id != snapshot.frame.frame_id:
        raise ValueError("Object Reconstruction frame does not match snapshot")
    if observation.target_instance_id != snapshot.target.instance_id:
        raise ValueError("Object Reconstruction target does not match snapshot")


def _robust_extent(values: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.quantile(values, 0.98, axis=0) - np.quantile(values, 0.02, axis=0)


def _normalize_extents(
    extents: NDArray[np.float64], depth_mode: DepthMode
) -> NDArray[np.float64]:
    values = np.maximum(np.asarray(extents, dtype=np.float64), 1e-6)
    if depth_mode is DepthMode.RELATIVE:
        values = values * (0.14 / float(np.max(values)))
    elif float(np.max(values)) > 0.32:
        values = values * (0.28 / float(np.max(values)))
    values[:2] = np.clip(values[:2], 0.015, 0.18)
    values[2] = np.clip(values[2], 0.02, 0.28)
    return values


def _classify_geometry(
    extents: NDArray[np.float64],
    *,
    raw_world_extents: NDArray[np.float64],
    observed_hidden_extent: float,
    appearance: TargetAppearance | None,
) -> ProxyGeometry:
    width, _hidden, height = (float(value) for value in extents)
    ordered = np.sort(extents)[::-1]
    long_ratio = ordered[0] / max(ordered[1], 1e-9)
    mask_elongation = 1.0 if appearance is None else appearance.mask_elongation
    fill_ratio = 0.0 if appearance is None else appearance.mask_bbox_fill_ratio
    oriented_fill_ratio = (
        fill_ratio
        if appearance is None
        else float(
            getattr(appearance, "mask_oriented_bbox_fill_ratio", 0.0) or fill_ratio
        )
    )
    circularity = 0.0 if appearance is None else appearance.mask_circularity
    raw_horizontal = np.maximum(np.asarray(raw_world_extents[:2], dtype=np.float64), 1e-9)
    horizontal_ratio = float(np.max(raw_horizontal) / np.min(raw_horizontal))
    vertical_ratio = float(raw_world_extents[2] / np.max(raw_horizontal))
    semantic_cylinder = (
        appearance is not None and appearance.proxy_geometry is ProxyGeometry.CYLINDER
    )
    rotational_support = observed_hidden_extent / max(width, 1e-9) >= 0.55
    silhouette_cylinder = semantic_cylinder or (
        mask_elongation >= 1.25 and oriented_fill_ratio < 0.82
    )
    round_horizontal_section = horizontal_ratio <= 1.25
    if (
        vertical_ratio >= 1.15
        and round_horizontal_section
        and rotational_support
        and silhouette_cylinder
    ):
        return ProxyGeometry.CYLINDER
    if long_ratio >= 2.25 and mask_elongation >= 1.55:
        return ProxyGeometry.CAPSULE
    if oriented_fill_ratio >= 0.80 or fill_ratio >= 0.80:
        return ProxyGeometry.BOX
    if circularity >= 0.66 or ordered[0] / max(ordered[-1], 1e-9) <= 1.55:
        return ProxyGeometry.ELLIPSOID
    return ProxyGeometry.ELLIPSOID


__all__ = [
    "OBJECT_RECONSTRUCTION_SCHEMA_VERSION",
    "ObjectReconstruction",
    "fallback_reconstruction",
    "reconstruct_object",
]
