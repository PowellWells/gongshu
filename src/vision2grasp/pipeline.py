"""Truth-free orchestration for one deterministic perception-to-grasp run."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from vision2grasp.contracts import (
    Detection2D,
    ExecutionResult,
    GraspCandidate,
    LocalizedTarget,
    RGBDFrame,
)
from vision2grasp.control import GraspExecutor
from vision2grasp.geometry import TargetLocalizer
from vision2grasp.grasp import GraspPlanner
from vision2grasp.perception import InstanceSegmenter
from vision2grasp.simulation import RGBDSimulator


class PipelinePhase(str, Enum):
    CAPTURE = "CAPTURE"
    DETECT = "DETECT"
    LOCALIZE = "LOCALIZE"
    PLAN = "PLAN"
    EXECUTE = "EXECUTE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Vision2GraspPipelineConfig:
    """Deterministic selection rules for the single-target MVP."""

    target_class_priority: tuple[str, ...] = ("bottle", "cup")

    def __post_init__(self) -> None:
        normalized = tuple(name.strip().lower() for name in self.target_class_priority)
        if not normalized or any(not name for name in normalized):
            raise ValueError("target_class_priority must contain non-empty names")
        if len(set(normalized)) != len(normalized):
            raise ValueError("target_class_priority must not contain duplicates")
        object.__setattr__(self, "target_class_priority", normalized)


@dataclass(frozen=True, slots=True)
class PipelineRunResult:
    """Complete trace from public module outputs, without evaluation truth."""

    success: bool
    final_phase: PipelinePhase
    message: str
    visited_phases: tuple[PipelinePhase, ...]
    frame: RGBDFrame | None = None
    detections: tuple[Detection2D, ...] = ()
    selected_detection: Detection2D | None = None
    localized_target: LocalizedTarget | None = None
    candidates: tuple[GraspCandidate, ...] = ()
    selected_candidate: GraspCandidate | None = None
    execution: ExecutionResult | None = None

    def __post_init__(self) -> None:
        expected = PipelinePhase.SUCCEEDED if self.success else PipelinePhase.FAILED
        if self.final_phase is not expected:
            raise ValueError(
                f"final_phase must be {expected.value} when success={self.success}"
            )


class Vision2GraspPipeline:
    """Compose capture, segmentation, localization, planning and execution."""

    def __init__(
        self,
        simulator: RGBDSimulator,
        segmenter: InstanceSegmenter,
        localizer: TargetLocalizer,
        planner: GraspPlanner,
        executor: GraspExecutor,
        config: Vision2GraspPipelineConfig | None = None,
    ) -> None:
        self._simulator = simulator
        self._segmenter = segmenter
        self._localizer = localizer
        self._planner = planner
        self._executor = executor
        self._config = config or Vision2GraspPipelineConfig()

    def run(self) -> PipelineRunResult:
        """Run once after the caller resets the episode."""

        visited: list[PipelinePhase] = []
        payload: dict[str, object] = {}

        visited.append(PipelinePhase.CAPTURE)
        try:
            frame = self._simulator.capture()
            payload["frame"] = frame
        except (KeyError, RuntimeError, ValueError) as error:
            return self._failure(visited, f"capture failed: {error}", payload)

        visited.append(PipelinePhase.DETECT)
        try:
            detections = tuple(self._segmenter.predict(frame))
            payload["detections"] = detections
            if not detections:
                return self._failure(
                    visited, "detection produced no target instances", payload
                )
            selected_detection = self._select_detection(detections)
            payload["selected_detection"] = selected_detection
        except (FileNotFoundError, KeyError, RuntimeError, ValueError) as error:
            return self._failure(visited, f"detection failed: {error}", payload)

        visited.append(PipelinePhase.LOCALIZE)
        try:
            localized_target = self._localizer.localize(frame, selected_detection)
            payload["localized_target"] = localized_target
        except (KeyError, RuntimeError, ValueError) as error:
            return self._failure(visited, f"localization failed: {error}", payload)

        visited.append(PipelinePhase.PLAN)
        try:
            candidates = tuple(self._planner.plan(localized_target))
            payload["candidates"] = candidates
            executable = tuple(
                candidate for candidate in candidates if candidate.reachable
            )
            if not executable:
                return self._failure(
                    visited, "planning produced no reachable candidates", payload
                )
            selected_candidate = sorted(
                executable,
                key=lambda candidate: (-candidate.score, candidate.candidate_id),
            )[0]
            payload["selected_candidate"] = selected_candidate
        except (KeyError, RuntimeError, ValueError) as error:
            return self._failure(visited, f"planning failed: {error}", payload)

        visited.append(PipelinePhase.EXECUTE)
        try:
            execution = self._executor.execute(selected_candidate)
            payload["execution"] = execution
        except (KeyError, RuntimeError, ValueError) as error:
            return self._failure(visited, f"execution failed: {error}", payload)
        if not execution.success:
            return self._failure(
                visited,
                f"execution failed: {execution.message}",
                payload,
            )

        visited.append(PipelinePhase.SUCCEEDED)
        return PipelineRunResult(
            success=True,
            final_phase=PipelinePhase.SUCCEEDED,
            message="truth-free perception-to-motion sequence completed",
            visited_phases=tuple(visited),
            **payload,
        )

    def _select_detection(
        self, detections: tuple[Detection2D, ...]
    ) -> Detection2D:
        priorities = {
            name: index for index, name in enumerate(self._config.target_class_priority)
        }
        return sorted(
            detections,
            key=lambda detection: (
                -detection.confidence,
                priorities.get(
                    detection.class_name.lower(), len(self._config.target_class_priority)
                ),
                -int(np.count_nonzero(detection.mask)),
                detection.bbox_xyxy,
                detection.class_id,
            ),
        )[0]

    @staticmethod
    def _failure(
        visited: list[PipelinePhase],
        message: str,
        payload: dict[str, object],
    ) -> PipelineRunResult:
        visited.append(PipelinePhase.FAILED)
        return PipelineRunResult(
            success=False,
            final_phase=PipelinePhase.FAILED,
            message=message,
            visited_phases=tuple(visited),
            **payload,
        )


__all__ = [
    "PipelinePhase",
    "PipelineRunResult",
    "Vision2GraspPipeline",
    "Vision2GraspPipelineConfig",
]
