"""Mask geometry mapped onto a manually calibrated tabletop plane."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from vision2grasp.contracts import (
    Detection2D,
    PlanarLocalizedTarget,
    RGBFrame,
    TableCalibration,
)

from .table_calibration import image_to_table


@dataclass(frozen=True, slots=True)
class PlanarTargetLocalizerConfig:
    minimum_mask_pixels: int = 30
    maximum_points: int = 4096
    extent_lower_quantile: float = 0.02
    extent_upper_quantile: float = 0.98

    def __post_init__(self) -> None:
        if self.minimum_mask_pixels < 3:
            raise ValueError("minimum_mask_pixels must be at least 3")
        if self.maximum_points < self.minimum_mask_pixels:
            raise ValueError("maximum_points must be at least minimum_mask_pixels")
        if not 0.0 <= self.extent_lower_quantile < 0.5:
            raise ValueError("extent_lower_quantile must be in [0, 0.5)")
        if not 0.5 < self.extent_upper_quantile <= 1.0:
            raise ValueError("extent_upper_quantile must be in (0.5, 1]")


class PlanarTableTargetLocalizer:
    """Estimate table XY, principal direction and planar extents from a mask."""

    def __init__(self, config: PlanarTargetLocalizerConfig | None = None) -> None:
        self._config = config or PlanarTargetLocalizerConfig()

    def localize(
        self,
        frame: RGBFrame,
        detection: Detection2D,
        calibration: TableCalibration,
    ) -> PlanarLocalizedTarget:
        height, width = frame.rgb.shape[:2]
        if (width, height) != (calibration.image_width, calibration.image_height):
            raise ValueError("frame size does not match the fixed table calibration")
        if detection.mask.shape != (height, width):
            raise ValueError("detection mask shape does not match RGB frame")

        rows, columns = np.nonzero(detection.mask)
        if rows.size < self._config.minimum_mask_pixels:
            raise ValueError("detection mask has too few pixels for planar geometry")
        moments = cv2.moments(detection.mask.astype(np.uint8), binaryImage=True)
        if moments["m00"] <= 0.0:
            raise ValueError("detection mask has no measurable area")
        center_image = np.array(
            [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]],
            dtype=np.float64,
        )
        center_table = image_to_table(calibration, center_image.reshape(1, 2))[0]

        count = rows.size
        if count > self._config.maximum_points:
            selected = np.linspace(
                0, count - 1, self._config.maximum_points, dtype=np.int64
            )
            rows = rows[selected]
            columns = columns[selected]
        points_image = np.column_stack((columns, rows)).astype(np.float64)
        points_table = image_to_table(calibration, points_image)
        centered = points_table - np.mean(points_table, axis=0)
        covariance = centered.T @ centered / points_table.shape[0]
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        order = np.argsort(eigenvalues)[::-1]
        major_variance = float(eigenvalues[order[0]])
        minor_variance = max(float(eigenvalues[order[1]]), 0.0)
        if major_variance <= np.finfo(np.float64).eps:
            raise ValueError("planar target variance is too small")
        major_axis = np.asarray(eigenvectors[:, order[0]], dtype=np.float64)
        dominant = int(np.argmax(np.abs(major_axis)))
        if major_axis[dominant] < 0.0:
            major_axis = -major_axis
        major_axis /= np.linalg.norm(major_axis)
        minor_axis = np.array([-major_axis[1], major_axis[0]], dtype=np.float64)
        major_projection = centered @ major_axis
        minor_projection = centered @ minor_axis
        lower = self._config.extent_lower_quantile
        upper = self._config.extent_upper_quantile
        length = float(np.quantile(major_projection, upper) - np.quantile(major_projection, lower))
        width_m = float(np.quantile(minor_projection, upper) - np.quantile(minor_projection, lower))
        if length <= 0.0 or width_m <= 0.0:
            raise ValueError("estimated planar target extents must be positive")
        circularity = float(np.clip(minor_variance / major_variance, 0.0, 1.0))
        yaw = float(np.arctan2(major_axis[1], major_axis[0]))
        return PlanarLocalizedTarget(
            detection=detection,
            center_image_px=center_image,
            center_table_m=np.asarray(center_table, dtype=np.float64),
            points_table_m=np.asarray(points_table, dtype=np.float64),
            principal_yaw_rad=yaw,
            estimated_width_m=width_m,
            estimated_length_m=length,
            circularity=circularity,
        )


__all__ = ["PlanarTableTargetLocalizer", "PlanarTargetLocalizerConfig"]
