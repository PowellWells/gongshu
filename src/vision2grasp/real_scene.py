"""One-frame real-scene bottle perception without simulation truth."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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
from vision2grasp.geometry import PlanarTableTargetLocalizer
from vision2grasp.grasp import PlanarTopGraspPlanner
from vision2grasp.perception import InstanceSegmenter
from vision2grasp.visualization import render_real_scene_overlay


class RealScenePhase(str, Enum):
    ACQUIRE = "ACQUIRE"
    DETECT = "DETECT"
    LOCALIZE = "LOCALIZE"
    PLAN = "PLAN"
    READY = "READY"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class RealSceneResult:
    success: bool
    phase: RealScenePhase
    message: str
    frame: RGBFrame
    detections: tuple[Detection2D, ...]
    selected_detection: Detection2D | None
    target: PlanarLocalizedTarget | None
    candidates: tuple[PlanarGraspCandidate, ...]
    overlay_rgb: NDArray[np.uint8]
    calibrated: bool

    def __post_init__(self) -> None:
        if self.overlay_rgb.shape != self.frame.rgb.shape or self.overlay_rgb.dtype != np.uint8:
            raise ValueError("overlay_rgb must match the source RGB frame")


class RealScenePerceptionPipeline:
    """Detect a bottle and, when calibrated, estimate tabletop grasp candidates."""

    def __init__(
        self,
        segmenter: InstanceSegmenter,
        localizer: PlanarTableTargetLocalizer | None = None,
        planner: PlanarTopGraspPlanner | None = None,
    ) -> None:
        self._segmenter = segmenter
        self._localizer = localizer or PlanarTableTargetLocalizer()
        self._planner = planner or PlanarTopGraspPlanner()

    def process(
        self, frame: RGBFrame, calibration: TableCalibration | None
    ) -> RealSceneResult:
        detections: tuple[Detection2D, ...] = ()
        selected: Detection2D | None = None
        target: PlanarLocalizedTarget | None = None
        candidates: tuple[PlanarGraspCandidate, ...] = ()
        try:
            detections = tuple(
                detection
                for detection in self._segmenter.predict(frame)
                if detection.class_name.lower() == "bottle"
            )
            if not detections:
                overlay = render_real_scene_overlay(
                    frame,
                    calibration=calibration,
                    detection=None,
                    target=None,
                    candidates=(),
                )
                return RealSceneResult(
                    success=False,
                    phase=RealScenePhase.DETECT,
                    message="no bottle detected",
                    frame=frame,
                    detections=(),
                    selected_detection=None,
                    target=None,
                    candidates=(),
                    overlay_rgb=overlay,
                    calibrated=calibration is not None,
                )
            selected = sorted(
                detections,
                key=lambda item: (
                    -item.confidence,
                    -int(np.count_nonzero(item.mask)),
                    item.bbox_xyxy,
                ),
            )[0]
            if calibration is not None:
                target = self._localizer.localize(frame, selected, calibration)
                candidates = self._planner.plan(target)
            overlay = render_real_scene_overlay(
                frame,
                calibration=calibration,
                detection=selected,
                target=target,
                candidates=candidates,
            )
            return RealSceneResult(
                success=True,
                phase=(RealScenePhase.READY if calibration is not None else RealScenePhase.DETECT),
                message=(
                    "real-scene bottle grasp candidates ready"
                    if calibration is not None
                    else "bottle detected; table calibration required for measured XY"
                ),
                frame=frame,
                detections=detections,
                selected_detection=selected,
                target=target,
                candidates=candidates,
                overlay_rgb=overlay,
                calibrated=calibration is not None,
            )
        except (KeyError, RuntimeError, ValueError) as error:
            overlay = render_real_scene_overlay(
                frame,
                calibration=calibration,
                detection=selected,
                target=None,
                candidates=(),
            )
            return RealSceneResult(
                success=False,
                phase=RealScenePhase.FAILED,
                message=str(error),
                frame=frame,
                detections=detections,
                selected_detection=selected,
                target=None,
                candidates=(),
                overlay_rgb=overlay,
                calibrated=calibration is not None,
            )


def encode_overlay_jpeg(result: RealSceneResult, *, quality: int = 88) -> bytes:
    if not 1 <= quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100")
    bgr = cv2.cvtColor(result.overlay_rgb, cv2.COLOR_RGB2BGR)
    ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise OSError("failed to encode real-scene overlay JPEG")
    return encoded.tobytes()


__all__ = [
    "RealScenePerceptionPipeline",
    "RealScenePhase",
    "RealSceneResult",
    "encode_overlay_jpeg",
]
