"""Thread-safe live processing state for the local real-scene web app."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import threading
import time

import cv2

from vision2grasp.contracts import RGBFrame, TableCalibration
from vision2grasp.geometry import (
    create_table_calibration,
    load_table_calibration,
    save_table_calibration,
)
from vision2grasp.real_scene import RealScenePerceptionPipeline
from vision2grasp.sources import FrameSource


class RealSceneProcessor:
    """Continuously acquire, infer, and publish immutable browser snapshots."""

    def __init__(
        self,
        pipeline: RealScenePerceptionPipeline,
        *,
        calibration_path: Path,
        target_fps: float = 2.0,
    ) -> None:
        if not 0.1 <= target_fps <= 30.0:
            raise ValueError("target_fps must be between 0.1 and 30")
        self._pipeline = pipeline
        self._calibration_path = Path(calibration_path)
        self._target_period_s = 1.0 / target_fps
        self._lock = threading.RLock()
        self._source: FrameSource | None = None
        self._source_kind = "none"
        self._calibration = self._load_calibration_if_available()
        self._latest_frame: RGBFrame | None = None
        self._latest_images: dict[str, bytes] = {}
        self._revision = 0
        self._snapshot: dict[str, object] = self._empty_snapshot()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="vision2grasp-real-scene",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
        with self._lock:
            source = self._source
            self._source = None
            if source is not None:
                source.close()

    def set_source(self, source: FrameSource, *, kind: str) -> None:
        if not kind.strip():
            raise ValueError("source kind must not be empty")
        with self._lock:
            previous = self._source
            self._source = source
            self._source_kind = kind
            self._latest_frame = None
            self._latest_images = {}
            self._snapshot = self._empty_snapshot(
                status="starting",
                message=f"opening {source.source_name}",
            )
            if previous is not None:
                previous.close()

    def set_calibration(
        self,
        *,
        image_points_px: list[list[float]],
        table_width_m: float,
        table_height_m: float,
    ) -> TableCalibration:
        with self._lock:
            frame = self._latest_frame
            if frame is None:
                raise RuntimeError("a real frame is required before calibration")
            height, width = frame.rgb.shape[:2]
            calibration = create_table_calibration(
                image_width=width,
                image_height=height,
                image_points_px=image_points_px,
                table_width_m=table_width_m,
                table_height_m=table_height_m,
            )
            save_table_calibration(calibration, self._calibration_path)
            self._calibration = calibration
            return calibration

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return deepcopy(self._snapshot)

    def image(self, kind: str) -> bytes | None:
        with self._lock:
            value = self._latest_images.get(kind)
            return None if value is None else bytes(value)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                with self._lock:
                    source = self._source
                    if source is None:
                        self._snapshot = self._empty_snapshot()
                if source is None:
                    self._stop_event.wait(0.2)
                    continue
                with self._lock:
                    frame = source.capture()
                    calibration = self._compatible_calibration(frame)
                    self._latest_frame = frame
                result = self._pipeline.process(frame, calibration)
                images = self._encode_views(result)
                snapshot = self._result_snapshot(result, source.source_name)
                with self._lock:
                    self._revision += 1
                    snapshot["revision"] = self._revision
                    self._latest_images = images
                    self._snapshot = snapshot
            except (KeyError, OSError, RuntimeError, ValueError) as error:
                with self._lock:
                    self._revision += 1
                    self._snapshot = self._empty_snapshot(
                        status="error",
                        message=str(error),
                    )
                    self._snapshot["revision"] = self._revision
            elapsed = time.monotonic() - started
            self._stop_event.wait(max(0.0, self._target_period_s - elapsed))

    def _compatible_calibration(self, frame: RGBFrame) -> TableCalibration | None:
        calibration = self._calibration
        if calibration is None:
            return None
        height, width = frame.rgb.shape[:2]
        if (width, height) != (calibration.image_width, calibration.image_height):
            return None
        return calibration

    @staticmethod
    def _jpeg(rgb) -> bytes:
        ok, encoded = cv2.imencode(
            ".jpg",
            cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
            [cv2.IMWRITE_JPEG_QUALITY, 88],
        )
        if not ok:
            raise OSError("failed to encode browser frame")
        return encoded.tobytes()

    def _encode_views(self, result) -> dict[str, bytes]:
        from vision2grasp.visualization import render_real_scene_overlay

        detection = result.selected_detection
        calibration = self._compatible_calibration(result.frame)
        detection_view = render_real_scene_overlay(
            result.frame,
            calibration=None,
            detection=detection,
            target=None,
            candidates=(),
        )
        spatial_view = render_real_scene_overlay(
            result.frame,
            calibration=calibration,
            detection=detection,
            target=result.target,
            candidates=(),
        )
        return {
            "live": self._jpeg(detection_view),
            "spatial": self._jpeg(spatial_view),
            "grasp": self._jpeg(result.overlay_rgb),
        }

    def _result_snapshot(self, result, source_name: str) -> dict[str, object]:
        target = None
        if result.selected_detection is not None:
            detection = result.selected_detection
            target = {
                "class_name": detection.class_name,
                "confidence": float(detection.confidence),
                "bbox_xyxy": [float(value) for value in detection.bbox_xyxy],
                "center_table_m": (
                    None
                    if result.target is None
                    else [float(value) for value in result.target.center_table_m]
                ),
                "principal_yaw_deg": (
                    None
                    if result.target is None
                    else float(result.target.principal_yaw_rad * 180.0 / 3.141592653589793)
                ),
                "estimated_width_m": (
                    None if result.target is None else float(result.target.estimated_width_m)
                ),
                "estimated_length_m": (
                    None if result.target is None else float(result.target.estimated_length_m)
                ),
                "provenance": {
                    "confidence": "vision",
                    "center_table_xy": "measured_calibration",
                    "yaw": "estimated_geometry",
                    "width": "estimated_geometry",
                },
            }
        candidates = [
            {
                "candidate_id": candidate.candidate_id,
                "rank": rank,
                "center_table_m": [float(value) for value in candidate.center_table_m],
                "yaw_deg": float(candidate.yaw_rad * 180.0 / 3.141592653589793),
                "estimated_gripper_width_m": float(candidate.estimated_gripper_width_m),
                "vision_score": float(candidate.vision_score),
                "geometry_score": float(candidate.geometry_score),
                "final_score": float(candidate.final_score),
                "width_feasible": bool(candidate.width_feasible),
                "simulation_validation": "NOT_RUN",
            }
            for rank, candidate in enumerate(result.candidates, start=1)
        ]
        frame_height, frame_width = result.frame.rgb.shape[:2]
        calibration = self._compatible_calibration(result.frame)
        return {
            "schema_version": "vision2grasp.real-scene/v1",
            "status": "ready" if result.success else "waiting",
            "phase": result.phase.value,
            "message": result.message,
            "source": {
                "kind": self._source_kind,
                "name": source_name,
            },
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "frame": {
                "frame_id": result.frame.frame_id,
                "width": frame_width,
                "height": frame_height,
            },
            "calibration": {
                "ready": calibration is not None,
                "method": "manual_four_point_ruler",
                "table_width_m": None if calibration is None else calibration.table_width_m,
                "table_height_m": None if calibration is None else calibration.table_height_m,
                "image_points_px": None if calibration is None else calibration.image_points_px.tolist(),
                "image_coverage_ratio": None if calibration is None else calibration.image_coverage_ratio,
            },
            "target": target,
            "candidates": candidates,
            "selected_candidate_id": candidates[0]["candidate_id"] if candidates else None,
            "simulation_validation": {
                "status": "NOT_RUN",
                "reachability": "NOT_RUN",
                "collision": "NOT_RUN",
                "gripper_width": "NOT_RUN",
                "lift_test": "NOT_RUN",
                "final_result": "NOT_RUN",
            },
            "revision": self._revision,
        }

    def _empty_snapshot(
        self, *, status: str = "idle", message: str = "no real input source"
    ) -> dict[str, object]:
        return {
            "schema_version": "vision2grasp.real-scene/v1",
            "status": status,
            "phase": "ACQUIRE",
            "message": message,
            "source": {"kind": self._source_kind, "name": None},
            "captured_at": None,
            "frame": None,
            "calibration": {
                "ready": False,
                "method": "manual_four_point_ruler",
            },
            "target": None,
            "candidates": [],
            "selected_candidate_id": None,
            "simulation_validation": {
                "status": "NOT_RUN",
                "reachability": "NOT_RUN",
                "collision": "NOT_RUN",
                "gripper_width": "NOT_RUN",
                "lift_test": "NOT_RUN",
                "final_result": "NOT_RUN",
            },
            "revision": self._revision,
        }

    def _load_calibration_if_available(self) -> TableCalibration | None:
        if not self._calibration_path.is_file():
            return None
        try:
            return load_table_calibration(self._calibration_path)
        except (KeyError, OSError, ValueError):
            return None


__all__ = ["RealSceneProcessor"]
