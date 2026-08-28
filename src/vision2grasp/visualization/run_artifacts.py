"""Export stable, truth-free artifacts for the local frontend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping

import cv2
import numpy as np
from numpy.typing import NDArray

from vision2grasp.contracts import (
    Detection2D,
    ExecutionPhase,
    GraspCandidate,
    RGBDFrame,
)
from vision2grasp.pipeline import PipelinePhase, PipelineRunResult


RUN_SCHEMA_VERSION = "vision2grasp.run/v1"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ExportedRunArtifacts:
    """Paths and parsed document produced by one export."""

    run_directory: Path
    run_json_path: Path
    document: Mapping[str, Any]


class RunArtifactExporter:
    """Write one immutable frontend run directory from public pipeline outputs."""

    def export(
        self,
        run: PipelineRunResult,
        *,
        output_root: Path,
        run_id: str,
        timestamp: datetime | None = None,
        final_frame: RGBDFrame | None = None,
    ) -> ExportedRunArtifacts:
        """Write ``run.json`` and available PNG views.

        The document deliberately excludes evaluation results and simulator truth.
        Every media path is relative to ``run.json`` and uses POSIX separators.
        Existing run directories are never overwritten.
        """

        if _RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise ValueError(
                "run_id must start with an alphanumeric character and contain only "
                "letters, digits, dot, underscore or hyphen"
            )

        recorded_at = timestamp or datetime.now().astimezone()
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")

        run_directory = Path(output_root) / run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        media_directory = run_directory / "media"
        media_directory.mkdir()

        media = self._write_media(
            run,
            media_directory=media_directory,
            final_frame=final_frame,
        )
        document = self._build_document(
            run,
            run_id=run_id,
            timestamp=recorded_at,
            media=media,
        )

        run_json_path = run_directory / "run.json"
        temporary_path = run_directory / "run.json.tmp"
        temporary_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(run_json_path)
        return ExportedRunArtifacts(run_directory, run_json_path, document)

    def _write_media(
        self,
        run: PipelineRunResult,
        *,
        media_directory: Path,
        final_frame: RGBDFrame | None,
    ) -> dict[str, dict[str, str] | None]:
        media: dict[str, dict[str, str] | None] = {
            "rgb": None,
            "depth": None,
            "grasp_overlay": None,
            "mujoco": None,
        }
        if run.frame is not None:
            rgb = _render_detection(run.frame, run.selected_detection)
            depth = _render_depth(run.frame.depth_m)
            grasp = _render_grasp_overlay(
                run.frame,
                run.selected_detection,
                run.selected_candidate,
            )
            _write_rgb_png(media_directory / "rgb.png", rgb)
            _write_rgb_png(media_directory / "depth.png", depth)
            _write_rgb_png(media_directory / "grasp_overlay.png", grasp)
            media["rgb"] = _media_entry("media/rgb.png", "RGB 检测")
            media["depth"] = _media_entry("media/depth.png", "深度图")
            media["grasp_overlay"] = _media_entry(
                "media/grasp_overlay.png", "抓取候选"
            )
        if final_frame is not None:
            _write_rgb_png(media_directory / "mujoco.png", final_frame.rgb)
            media["mujoco"] = _media_entry("media/mujoco.png", "MuJoCo 结果")
        return media

    @staticmethod
    def _build_document(
        run: PipelineRunResult,
        *,
        run_id: str,
        timestamp: datetime,
        media: Mapping[str, Mapping[str, str] | None],
    ) -> dict[str, Any]:
        target = None
        if run.localized_target is not None:
            detection = run.localized_target.detection
            frame = run.frame
            if frame is None:
                raise ValueError("localized target requires its source RGB-D frame")
            target = {
                "class_name": detection.class_name,
                "confidence": float(detection.confidence),
                "bbox_xyxy": [float(value) for value in detection.bbox_xyxy],
                "image_size_px": {
                    "width": int(frame.intrinsics.width),
                    "height": int(frame.intrinsics.height),
                },
                "centroid_world_m": [
                    float(value) for value in run.localized_target.centroid_world_m
                ],
            }

        ranked_candidates = sorted(
            run.candidates,
            key=lambda candidate: (-candidate.score, candidate.candidate_id),
        )
        candidates = [
            {
                "candidate_id": candidate.candidate_id,
                "rank": rank,
                "position_world_m": [
                    float(value) for value in candidate.world_from_grasp[:3, 3]
                ],
                "orientation_world_rpy_deg": _rotation_to_rpy_degrees(
                    candidate.world_from_grasp[:3, :3]
                ),
                "gripper_width_m": float(candidate.gripper_width_m),
                "score": float(candidate.score),
                "reachable": bool(candidate.reachable),
            }
            for rank, candidate in enumerate(ranked_candidates, start=1)
        ]

        execution = None
        if run.execution is not None:
            execution = {
                "success": bool(run.execution.success),
                "final_phase": (
                    "SUCCESS" if run.execution.success else "FAILURE"
                ),
                "message": run.execution.message,
                "visited_phases": [
                    phase.value for phase in run.execution.visited_phases
                ],
            }

        return {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "timestamp": timestamp.isoformat(timespec="seconds"),
            "status": "success" if run.success else "failure",
            "stage": "SUCCESS" if run.success else "FAILURE",
            "media": dict(media),
            "target": target,
            "candidates": candidates,
            "selected_candidate_id": (
                None
                if run.selected_candidate is None
                else run.selected_candidate.candidate_id
            ),
            "execution": execution,
            "events": _events(run),
        }


def make_run_id(prefix: str, *, timestamp: datetime | None = None) -> str:
    """Create a filesystem-safe run id with local time."""

    recorded_at = timestamp or datetime.now().astimezone()
    if _RUN_ID_PATTERN.fullmatch(prefix) is None:
        raise ValueError("run id prefix contains unsupported characters")
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    time_component = recorded_at.strftime("%Y%m%dT%H%M%S%f%z")
    safe_time_component = time_component.replace("+", "p").replace("-", "m")
    return f"{prefix}-{safe_time_component}"


def _events(run: PipelineRunResult) -> list[dict[str, str | None]]:
    events: list[dict[str, str | None]] = []
    for phase in run.visited_phases:
        terminal_failure = phase is PipelinePhase.FAILED
        events.append(
            {
                "timestamp": None,
                "stage": phase.value,
                "status": "failed" if terminal_failure else "completed",
                "message": run.message if terminal_failure else _pipeline_message(phase),
            }
        )
        if phase is PipelinePhase.EXECUTE and run.execution is not None:
            for execution_phase in run.execution.visited_phases:
                execution_failed = execution_phase is ExecutionPhase.FAILED
                events.append(
                    {
                        "timestamp": None,
                        "stage": execution_phase.value,
                        "status": "failed" if execution_failed else "completed",
                        "message": (
                            run.execution.message
                            if execution_phase
                            in (ExecutionPhase.SUCCEEDED, ExecutionPhase.FAILED)
                            else _execution_message(execution_phase)
                        ),
                    }
                )
    return events


def _pipeline_message(phase: PipelinePhase) -> str:
    return {
        PipelinePhase.CAPTURE: "Captured synchronized RGB-D frame",
        PipelinePhase.DETECT: "Completed instance segmentation",
        PipelinePhase.LOCALIZE: "Localized target in world coordinates",
        PipelinePhase.PLAN: "Generated and ranked grasp candidates",
        PipelinePhase.EXECUTE: "Executed selected grasp candidate",
        PipelinePhase.SUCCEEDED: "Perception-to-motion sequence completed",
        PipelinePhase.FAILED: "Pipeline failed",
    }[phase]


def _execution_message(phase: ExecutionPhase) -> str:
    return {
        ExecutionPhase.HOME: "Initialized robot at home pose",
        ExecutionPhase.PREGRASP: "Moved to pregrasp pose",
        ExecutionPhase.DESCEND: "Descended to grasp pose",
        ExecutionPhase.CLOSE: "Closed gripper",
        ExecutionPhase.LIFT: "Lifted grasp candidate",
        ExecutionPhase.RETURN_HOME: "Returned robot to home pose",
        ExecutionPhase.SUCCEEDED: "Motion sequence completed",
        ExecutionPhase.FAILED: "Motion sequence failed",
    }[phase]


def _media_entry(path: str, label: str) -> dict[str, str]:
    return {"path": path, "kind": "image", "label": label}


def _render_detection(
    frame: RGBDFrame, detection: Detection2D | None
) -> NDArray[np.uint8]:
    image = frame.rgb.copy()
    if detection is None:
        return image
    if detection.mask.shape != image.shape[:2]:
        raise ValueError("detection mask shape does not match RGB frame")

    overlay = image.copy()
    overlay[detection.mask] = np.array([0, 210, 255], dtype=np.uint8)
    image = cv2.addWeighted(image, 0.72, overlay, 0.28, 0.0)
    x1, y1, x2, y2 = (int(round(value)) for value in detection.bbox_xyxy)
    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 220, 255), 2)
    label = f"{detection.class_name} {detection.confidence:.3f}"
    cv2.putText(
        image,
        label,
        (max(0, x1), max(18, y1 - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return image


def _render_depth(depth_m: NDArray[np.floating]) -> NDArray[np.uint8]:
    depth = np.asarray(depth_m, dtype=np.float32)
    valid = np.isfinite(depth) & (depth > 0.0)
    normalized = np.zeros(depth.shape, dtype=np.uint8)
    if np.any(valid):
        lower, upper = np.percentile(depth[valid], [2.0, 98.0])
        if float(upper - lower) < 1e-9:
            normalized[valid] = 127
        else:
            scaled = (depth[valid] - lower) / (upper - lower)
            normalized[valid] = np.clip(scaled * 255.0, 0.0, 255.0).astype(
                np.uint8
            )
    colored_bgr = cv2.applyColorMap(255 - normalized, cv2.COLORMAP_TURBO)
    colored_bgr[~valid] = 0
    return cv2.cvtColor(colored_bgr, cv2.COLOR_BGR2RGB)


def _render_grasp_overlay(
    frame: RGBDFrame,
    detection: Detection2D | None,
    candidate: GraspCandidate | None,
) -> NDArray[np.uint8]:
    image = _render_detection(frame, detection)
    if candidate is None:
        return image

    origin = candidate.world_from_grasp[:3, 3]
    rotation = candidate.world_from_grasp[:3, :3]
    axis_length_m = 0.04
    points_world = np.vstack(
        [origin, origin + rotation[:, 0] * axis_length_m, origin + rotation[:, 1] * axis_length_m]
    )
    projected = _project_world_points(frame, points_world)
    if projected is not None:
        center, closing_axis, long_axis = projected
        center_xy = tuple(np.rint(center).astype(int))
        cv2.circle(image, center_xy, 6, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.line(
            image,
            center_xy,
            tuple(np.rint(closing_axis).astype(int)),
            (255, 70, 70),
            3,
            cv2.LINE_AA,
        )
        cv2.line(
            image,
            center_xy,
            tuple(np.rint(long_axis).astype(int)),
            (80, 255, 120),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            image,
            f"score {candidate.score:.3f} | width {candidate.gripper_width_m:.3f} m",
            (12, image.shape[0] - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    return image


def _project_world_points(
    frame: RGBDFrame, points_world: NDArray[np.float64]
) -> NDArray[np.float64] | None:
    camera_from_world = np.linalg.inv(frame.world_from_camera)
    homogeneous = np.column_stack((points_world, np.ones(points_world.shape[0])))
    points_camera = (camera_from_world @ homogeneous.T).T[:, :3]
    if np.any(points_camera[:, 2] <= 1e-8):
        return None
    intrinsics = frame.intrinsics
    pixels = np.empty((points_camera.shape[0], 2), dtype=np.float64)
    pixels[:, 0] = (
        intrinsics.fx * points_camera[:, 0] / points_camera[:, 2] + intrinsics.cx
    )
    pixels[:, 1] = (
        intrinsics.fy * points_camera[:, 1] / points_camera[:, 2] + intrinsics.cy
    )
    return pixels


def _rotation_to_rpy_degrees(rotation: NDArray[np.float64]) -> list[float]:
    """Return fixed-world XYZ roll, pitch and yaw angles in degrees."""

    horizontal = float(np.hypot(rotation[0, 0], rotation[1, 0]))
    singular = horizontal < 1e-8
    if not singular:
        roll = np.arctan2(rotation[2, 1], rotation[2, 2])
        pitch = np.arctan2(-rotation[2, 0], horizontal)
        yaw = np.arctan2(rotation[1, 0], rotation[0, 0])
    else:
        roll = np.arctan2(-rotation[1, 2], rotation[1, 1])
        pitch = np.arctan2(-rotation[2, 0], horizontal)
        yaw = 0.0
    return [float(value) for value in np.rad2deg([roll, pitch, yaw])]


def _write_rgb_png(path: Path, image: NDArray[np.uint8]) -> None:
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("PNG view must be an HxWx3 uint8 RGB image")
    if not cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR)):
        raise OSError(f"failed to write image: {path}")


__all__ = [
    "ExportedRunArtifacts",
    "RUN_SCHEMA_VERSION",
    "RunArtifactExporter",
    "make_run_id",
]
