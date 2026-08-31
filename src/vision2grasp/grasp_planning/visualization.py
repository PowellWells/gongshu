"""Render real grasp maps, Top-K candidates, and rejection evidence."""

from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import GraspCandidate, GraspPlan, GraspPlanningOutcome, PlanningMode


def render_grasp_views(
    snapshot: TargetSceneSnapshot,
    outcome: GraspPlanningOutcome,
    mode: PlanningMode,
) -> dict[str, NDArray[np.uint8]]:
    return {
        "quality": _map_overlay(snapshot, outcome.maps.quality, cv2.COLORMAP_TURBO, "QUALITY MAP"),
        "angle": _angle_overlay(snapshot, outcome.maps.angle),
        "width": _map_overlay(snapshot, outcome.maps.width_px, cv2.COLORMAP_VIRIDIS, "WIDTH MAP"),
        "candidates": _candidate_overlay(snapshot, outcome, mode),
    }


def render_grasp_overlay(snapshot: TargetSceneSnapshot, plan: GraspPlan) -> NDArray[np.uint8]:
    """Compatibility renderer for the retained geometric planner."""

    image = snapshot.frame.rgb.copy()
    if plan.candidates:
        for candidate in plan.candidates:
            _draw_candidate(
                image,
                candidate,
                best=candidate.candidate_id == plan.best_candidate_id,
                draw_rejected=True,
            )
    else:
        center = tuple(int(round(value)) for value in snapshot.target.centroid_2d)
        direction = np.array(plan.closing_vector[:2], dtype=np.float64, copy=True)
        direction /= max(float(np.linalg.norm(direction)), 1e-9)
        span = max(min(snapshot.target.bbox_xyxy[2] - snapshot.target.bbox_xyxy[0], snapshot.target.bbox_xyxy[3] - snapshot.target.bbox_xyxy[1]) * 0.35, 18.0)
        cv2.line(
            image,
            tuple(np.rint(np.asarray(center) - direction * span).astype(int)),
            tuple(np.rint(np.asarray(center) + direction * span).astype(int)),
            (255, 220, 95),
            4,
            cv2.LINE_AA,
        )
    _draw_target_contour(image, snapshot)
    cv2.putText(image, "BEST GRASP", (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.78, (255, 226, 108), 2, cv2.LINE_AA)
    return image


def _map_overlay(
    snapshot: TargetSceneSnapshot,
    values: NDArray[np.float32],
    color_map: int,
    title: str,
) -> NDArray[np.uint8]:
    image = snapshot.frame.rgb.copy()
    mask = snapshot.target.mask
    visible = values[mask]
    if visible.size:
        lower, upper = np.quantile(visible, [0.02, 0.98])
        scale = max(float(upper - lower), 1e-6)
        normalized = np.clip((values - lower) / scale, 0.0, 1.0)
    else:
        normalized = np.zeros(values.shape, dtype=np.float32)
    heat_bgr = cv2.applyColorMap(np.rint(normalized * 255.0).astype(np.uint8), color_map)
    heat_rgb = cv2.cvtColor(heat_bgr, cv2.COLOR_BGR2RGB)
    blended = cv2.addWeighted(image, 0.42, heat_rgb, 0.58, 0.0)
    image[mask] = blended[mask]
    _draw_target_contour(image, snapshot)
    cv2.putText(image, title, (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (245, 250, 255), 2, cv2.LINE_AA)
    return image


def _angle_overlay(
    snapshot: TargetSceneSnapshot,
    angle: NDArray[np.float32],
) -> NDArray[np.uint8]:
    image = snapshot.frame.rgb.copy()
    mask = snapshot.target.mask
    hue = np.mod((angle + np.pi / 2.0) / np.pi, 1.0)
    hsv = np.zeros((*angle.shape, 3), dtype=np.uint8)
    hsv[..., 0] = np.rint(hue * 179.0).astype(np.uint8)
    hsv[..., 1] = 225
    hsv[..., 2] = 245
    angle_rgb = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    blended = cv2.addWeighted(image, 0.42, angle_rgb, 0.58, 0.0)
    image[mask] = blended[mask]
    _draw_target_contour(image, snapshot)
    cv2.putText(image, "ANGLE MAP", (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (245, 250, 255), 2, cv2.LINE_AA)
    return image


def _candidate_overlay(
    snapshot: TargetSceneSnapshot,
    outcome: GraspPlanningOutcome,
    mode: PlanningMode,
) -> NDArray[np.uint8]:
    image = snapshot.frame.rgb.copy()
    _draw_target_contour(image, snapshot)
    best_id = None if outcome.plan is None else outcome.plan.best_candidate_id
    for candidate in outcome.candidates:
        if mode is PlanningMode.DEMO and not candidate.executable:
            continue
        _draw_candidate(
            image,
            candidate,
            best=candidate.candidate_id == best_id,
            draw_rejected=mode is PlanningMode.RESEARCH,
        )
    if outcome.ready:
        title = "BEST EXECUTABLE GRASP"
        color = (255, 226, 108)
    else:
        title = f"PLANNING REJECTED: {outcome.rejection_reason}"
        color = (255, 104, 104)
    cv2.putText(image, title, (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.64, color, 2, cv2.LINE_AA)
    mode_text = "RESEARCH: TOP-K + REJECTS" if mode is PlanningMode.RESEARCH else "DEMO: GRASPABILITY PREFLIGHT"
    cv2.putText(image, mode_text, (24, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (220, 236, 246), 1, cv2.LINE_AA)
    return image


def _draw_candidate(
    image: NDArray[np.uint8],
    candidate: GraspCandidate,
    *,
    best: bool,
    draw_rejected: bool,
) -> None:
    if candidate.center_uv is None or candidate.width_px is None:
        return
    if not candidate.executable and not draw_rejected:
        return
    center = np.asarray(candidate.center_uv, dtype=np.float64)
    closing = np.array([np.cos(candidate.grasp_angle), np.sin(candidate.grasp_angle)], dtype=np.float64)
    tangent = np.array([-closing[1], closing[0]], dtype=np.float64)
    jaw_half_span = candidate.width_px * 0.5
    finger_half_length = max(candidate.width_px * 0.24, 5.0)
    if best:
        color = (255, 226, 78)
        thickness = 4
    elif candidate.executable:
        color = (70, 238, 188)
        thickness = 2
    else:
        color = (255, 82, 92)
        thickness = 2
    for sign in (-1.0, 1.0):
        jaw = center + closing * jaw_half_span * sign
        start = jaw - tangent * finger_half_length
        end = jaw + tangent * finger_half_length
        cv2.line(image, tuple(np.rint(start).astype(int)), tuple(np.rint(end).astype(int)), color, thickness, cv2.LINE_AA)
    cv2.line(
        image,
        tuple(np.rint(center - closing * jaw_half_span).astype(int)),
        tuple(np.rint(center + closing * jaw_half_span).astype(int)),
        color,
        max(thickness - 1, 1),
        cv2.LINE_AA,
    )
    label = f"{candidate.candidate_id.split('-')[-1]} q={candidate.quality_score:.2f}"
    if not candidate.executable:
        label += f" {candidate.rejection_reasons[0]}"
    origin = tuple(np.rint(center + np.array([7.0, -7.0])).astype(int))
    cv2.putText(image, label, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.36, color, 1, cv2.LINE_AA)


def _draw_target_contour(image: NDArray[np.uint8], snapshot: TargetSceneSnapshot) -> None:
    contours, _ = cv2.findContours(
        snapshot.target.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(image, contours, -1, (78, 244, 228), 2, cv2.LINE_AA)


def encode_jpeg(image_rgb: NDArray[np.uint8], *, quality: int = 92) -> bytes:
    ok, encoded = cv2.imencode(
        ".jpg",
        cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    if not ok:
        raise RuntimeError("could not encode grasp visualization")
    return encoded.tobytes()
