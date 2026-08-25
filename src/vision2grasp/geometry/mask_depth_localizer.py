"""Mask-based RGB-D backprojection and world-frame localization."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import Detection2D, LocalizedTarget, RGBDFrame


@dataclass(frozen=True, slots=True)
class MaskDepthLocalizerConfig:
    """Validation, robust depth filtering, and point-cloud size limits."""

    minimum_valid_depth_ratio: float = 0.50
    minimum_points: int = 30
    maximum_points: int = 4096
    outlier_mad_scale: float = 3.5
    minimum_depth_band_m: float = 0.01

    def __post_init__(self) -> None:
        if not 0.0 < self.minimum_valid_depth_ratio <= 1.0:
            raise ValueError("minimum_valid_depth_ratio must be in (0, 1]")
        if self.minimum_points <= 0:
            raise ValueError("minimum_points must be positive")
        if self.maximum_points < self.minimum_points:
            raise ValueError("maximum_points must be at least minimum_points")
        if self.outlier_mad_scale <= 0.0:
            raise ValueError("outlier_mad_scale must be positive")
        if self.minimum_depth_band_m <= 0.0:
            raise ValueError("minimum_depth_band_m must be positive")


class MaskDepthTargetLocalizer:
    """Localize an instance mask using metric depth and calibrated camera poses."""

    def __init__(self, config: MaskDepthLocalizerConfig | None = None) -> None:
        self._config = config or MaskDepthLocalizerConfig()

    def localize(
        self, frame: RGBDFrame, detection: Detection2D
    ) -> LocalizedTarget:
        """Return a filtered local point cloud and centroid in world coordinates."""

        expected_shape = (frame.intrinsics.height, frame.intrinsics.width)
        if detection.mask.shape != expected_shape:
            raise ValueError(
                f"detection mask must have shape {expected_shape}, "
                f"got {detection.mask.shape}"
            )

        mask_pixels = int(np.count_nonzero(detection.mask))
        if mask_pixels == 0:
            raise ValueError("detection mask must contain at least one pixel")

        depth = np.asarray(frame.depth_m)
        valid_depth = np.isfinite(depth) & (depth > 0.0)
        mask_valid_depth = detection.mask & valid_depth
        valid_count = int(np.count_nonzero(mask_valid_depth))
        depth_valid_ratio = valid_count / mask_pixels
        if depth_valid_ratio < self._config.minimum_valid_depth_ratio:
            raise ValueError(
                "valid depth ratio below minimum: "
                f"{depth_valid_ratio:.6f} < "
                f"{self._config.minimum_valid_depth_ratio:.6f}"
            )
        if valid_count < self._config.minimum_points:
            raise ValueError(
                f"valid depth points below minimum: {valid_count} < "
                f"{self._config.minimum_points}"
            )

        rows, columns = np.nonzero(mask_valid_depth)
        depths_m = np.asarray(depth[rows, columns], dtype=np.float64)
        inliers = self._depth_inliers(depths_m)
        rows = rows[inliers]
        columns = columns[inliers]
        depths_m = depths_m[inliers]
        if depths_m.size < self._config.minimum_points:
            raise ValueError(
                f"depth inliers below minimum: {depths_m.size} < "
                f"{self._config.minimum_points}"
            )

        world_from_camera = self._validated_world_from_camera(
            frame.world_from_camera
        )
        x_camera_m, y_camera_m = self._backproject_xy(
            columns, rows, depths_m, frame
        )

        centroid_camera_m = np.array(
            [
                np.mean(x_camera_m),
                np.mean(y_camera_m),
                np.mean(depths_m),
                1.0,
            ],
            dtype=np.float64,
        )
        centroid_world_m = (world_from_camera @ centroid_camera_m)[:3]

        selected = self._sample_indices(depths_m.size)
        points_camera_m = np.column_stack(
            (
                x_camera_m[selected],
                y_camera_m[selected],
                depths_m[selected],
                np.ones(selected.size, dtype=np.float64),
            )
        )
        points_world_m = (world_from_camera @ points_camera_m.T).T[:, :3]

        if not np.all(np.isfinite(centroid_world_m)) or not np.all(
            np.isfinite(points_world_m)
        ):
            raise ValueError("localized world geometry must contain only finite values")

        return LocalizedTarget(
            detection=detection,
            centroid_world_m=np.asarray(centroid_world_m, dtype=np.float64),
            points_world_m=np.asarray(points_world_m, dtype=np.float64),
            depth_valid_ratio=float(depth_valid_ratio),
        )

    def _depth_inliers(self, depths_m: NDArray[np.float64]) -> NDArray[np.bool_]:
        median_depth = float(np.median(depths_m))
        median_absolute_deviation = float(
            np.median(np.abs(depths_m - median_depth))
        )
        robust_sigma_m = 1.4826 * median_absolute_deviation
        half_band_m = max(
            self._config.minimum_depth_band_m,
            self._config.outlier_mad_scale * robust_sigma_m,
        )
        return np.asarray(
            np.abs(depths_m - median_depth) <= half_band_m,
            dtype=np.bool_,
        )

    def _backproject_xy(
        self,
        columns: NDArray[np.intp],
        rows: NDArray[np.intp],
        depths_m: NDArray[np.float64],
        frame: RGBDFrame,
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        intrinsics = frame.intrinsics
        columns_f64 = columns.astype(np.float64, copy=False)
        rows_f64 = rows.astype(np.float64, copy=False)
        x_camera_m = (columns_f64 - intrinsics.cx) * depths_m / intrinsics.fx
        y_camera_m = (rows_f64 - intrinsics.cy) * depths_m / intrinsics.fy
        return x_camera_m, y_camera_m

    def _sample_indices(self, point_count: int) -> NDArray[np.int64]:
        if point_count <= self._config.maximum_points:
            return np.arange(point_count, dtype=np.int64)
        return np.linspace(
            0,
            point_count - 1,
            num=self._config.maximum_points,
            dtype=np.int64,
        )

    @staticmethod
    def _validated_world_from_camera(
        matrix: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        transform = np.asarray(matrix, dtype=np.float64)
        if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
            raise ValueError("world_from_camera must be a finite 4x4 matrix")
        if not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0], atol=1e-9):
            raise ValueError("world_from_camera must have a homogeneous final row")

        rotation = transform[:3, :3]
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-7):
            raise ValueError("world_from_camera rotation must be orthonormal")
        if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-7):
            raise ValueError("world_from_camera rotation must have determinant +1")
        return transform

