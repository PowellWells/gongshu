"""Manual ruler-and-four-click calibration for a fixed tabletop camera."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import TableCalibration


CALIBRATION_SCHEMA_VERSION = "vision2grasp.table-calibration/v1"


def create_table_calibration(
    *,
    image_width: int,
    image_height: int,
    image_points_px: NDArray[np.floating[Any]],
    table_width_m: float,
    table_height_m: float,
) -> TableCalibration:
    """Map ordered clicks ``origin, +X, +X+Y, +Y`` to measured table XY."""

    if image_width <= 0 or image_height <= 0:
        raise ValueError("image dimensions must be positive")
    if not 0.05 <= table_width_m <= 5.0 or not 0.05 <= table_height_m <= 5.0:
        raise ValueError("measured table dimensions must be between 0.05 m and 5 m")

    points = np.asarray(image_points_px, dtype=np.float64)
    if points.shape != (4, 2) or not np.all(np.isfinite(points)):
        raise ValueError("image_points_px must be a finite 4x2 array")
    if np.any(points[:, 0] < 0.0) or np.any(points[:, 0] >= image_width):
        raise ValueError("calibration X pixels must lie inside the image")
    if np.any(points[:, 1] < 0.0) or np.any(points[:, 1] >= image_height):
        raise ValueError("calibration Y pixels must lie inside the image")
    contour = points.astype(np.float32).reshape(-1, 1, 2)
    if not cv2.isContourConvex(contour):
        raise ValueError("calibration clicks must form a convex ordered quadrilateral")
    area_px2 = abs(float(cv2.contourArea(contour)))
    image_area_px2 = float(image_width * image_height)
    coverage = area_px2 / image_area_px2
    if coverage < 0.02:
        raise ValueError("calibration quadrilateral must cover at least 2% of the image")

    table_points = np.array(
        [
            [0.0, 0.0],
            [table_width_m, 0.0],
            [table_width_m, table_height_m],
            [0.0, table_height_m],
        ],
        dtype=np.float32,
    )
    table_from_image = cv2.getPerspectiveTransform(
        points.astype(np.float32), table_points
    ).astype(np.float64)
    image_from_table = cv2.getPerspectiveTransform(
        table_points, points.astype(np.float32)
    ).astype(np.float64)
    return TableCalibration(
        image_width=image_width,
        image_height=image_height,
        table_width_m=float(table_width_m),
        table_height_m=float(table_height_m),
        image_points_px=points.copy(),
        table_from_image=table_from_image,
        image_from_table=image_from_table,
        image_coverage_ratio=float(coverage),
    )


def image_to_table(
    calibration: TableCalibration,
    points_px: NDArray[np.floating[Any]],
) -> NDArray[np.float64]:
    return _transform_points(points_px, calibration.table_from_image)


def table_to_image(
    calibration: TableCalibration,
    points_table_m: NDArray[np.floating[Any]],
) -> NDArray[np.float64]:
    return _transform_points(points_table_m, calibration.image_from_table)


def _transform_points(
    points: NDArray[np.floating[Any]], matrix: NDArray[np.float64]
) -> NDArray[np.float64]:
    array = np.asarray(points, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 2 or not np.all(np.isfinite(array)):
        raise ValueError("points must have finite shape (N, 2)")
    transformed = cv2.perspectiveTransform(
        array.astype(np.float64).reshape(1, -1, 2), matrix
    ).reshape(-1, 2)
    if not np.all(np.isfinite(transformed)):
        raise ValueError("calibration transform produced non-finite coordinates")
    return np.asarray(transformed, dtype=np.float64)


def save_table_calibration(calibration: TableCalibration, path: Path) -> None:
    document = {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "image_size_px": {
            "width": calibration.image_width,
            "height": calibration.image_height,
        },
        "table_size_m": {
            "width": calibration.table_width_m,
            "height": calibration.table_height_m,
        },
        "image_points_px": calibration.image_points_px.tolist(),
        "image_coverage_ratio": calibration.image_coverage_ratio,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def load_table_calibration(path: Path) -> TableCalibration:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        raise ValueError("unsupported table calibration schema")
    image_size = document["image_size_px"]
    table_size = document["table_size_m"]
    return create_table_calibration(
        image_width=int(image_size["width"]),
        image_height=int(image_size["height"]),
        image_points_px=np.asarray(document["image_points_px"], dtype=np.float64),
        table_width_m=float(table_size["width"]),
        table_height_m=float(table_size["height"]),
    )


__all__ = [
    "CALIBRATION_SCHEMA_VERSION",
    "create_table_calibration",
    "image_to_table",
    "load_table_calibration",
    "save_table_calibration",
    "table_to_image",
]
