"""Optional bridge to the installed Xiezhi/Mayflower decision runtime."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .contracts import GongshuDecision, GongshuObservation


class XiezhiUnavailableError(RuntimeError):
    """Raised only when an explicitly enabled Xiezhi backend cannot load."""


def _quaternion_xyzw(rotation: NDArray[np.float64]) -> tuple[float, float, float, float]:
    """Convert a proper 3x3 rotation matrix at the adapter boundary."""
    trace = float(np.trace(rotation))
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
        w = 0.25 * scale
    else:
        index = int(np.argmax(np.diag(rotation)))
        if index == 0:
            scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2
            x, y, z, w = 0.25 * scale, (rotation[0, 1] + rotation[1, 0]) / scale, (
                rotation[0, 2] + rotation[2, 0]
            ) / scale, (rotation[2, 1] - rotation[1, 2]) / scale
        elif index == 1:
            scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2
            x, y, z, w = (rotation[0, 1] + rotation[1, 0]) / scale, 0.25 * scale, (
                rotation[1, 2] + rotation[2, 1]
            ) / scale, (rotation[0, 2] - rotation[2, 0]) / scale
        else:
            scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2
            x, y, z, w = (rotation[0, 2] + rotation[2, 0]) / scale, (
                rotation[1, 2] + rotation[2, 1]
            ) / scale, 0.25 * scale, (rotation[1, 0] - rotation[0, 1]) / scale
    quaternion = np.asarray((x, y, z, w), dtype=np.float64)
    quaternion /= np.linalg.norm(quaternion)
    return tuple(float(value) for value in quaternion)


class MayflowerXiezhiDecisionBackend:
    """Translate Gongshu evidence and invoke a policy from Xiezhi's registry."""

    _SKILLS = ("ExecuteGrasp", "Reobserve", "ChangeViewpoint", "Recover", "Abort")

    def __init__(self, algorithm: str = "rule_based") -> None:
        try:
            from xiezhi.runtime import default_algorithm_registry
        except ImportError as error:
            raise XiezhiUnavailableError(
                "Xiezhi is enabled but its runtime is not installed or importable"
            ) from error
        registry = default_algorithm_registry()
        try:
            self._policy = registry.create(algorithm)
        except ValueError as error:
            raise XiezhiUnavailableError(str(error)) from error

    def decide(self, observation: GongshuObservation) -> GongshuDecision:
        try:
            from grasp_decision.core.interfaces import MemorySnapshot, SkillSpec
            from grasp_decision.core.serialization import to_jsonable
            from grasp_decision.core.types import (
                DecisionContext,
                EpisodeContext,
                GraspCandidate as XiezhiGraspCandidate,
                ObjectBelief,
                Pose6D,
                PoseHypothesis,
                RobotBeliefState,
                TaskSpec,
                UncertaintyEstimate,
                UncertaintyKind,
            )
        except ImportError as error:
            raise XiezhiUnavailableError(
                "Xiezhi is enabled but the Mayflower contracts are unavailable"
            ) from error

        poses: list[Any] = []
        candidates: list[Any] = []
        for candidate in observation.candidates:
            transform = candidate.world_from_grasp
            pose = Pose6D(
                "world",
                tuple(float(value) for value in transform[:3, 3]),
                _quaternion_xyzw(transform[:3, :3]),
            )
            poses.append(pose)
            candidates.append(XiezhiGraspCandidate(
                candidate.candidate_id,
                observation.target_object_id,
                pose,
                candidate.gripper_width_m,
                raw_score=candidate.score,
            ))

        hypotheses = () if not poses else (PoseHypothesis(poses[0], 1.0),)
        objects = (ObjectBelief(observation.target_object_id, hypotheses),)
        uncertainties = []
        if observation.position_std_m is not None:
            uncertainties.append(UncertaintyEstimate(
                "position_std", observation.target_object_id, "gongshu_adapter_v0.1",
                observation.position_std_m, UncertaintyKind.PROXY, "m",
                evidence_ids=(observation.observation_id,),
            ))
        if observation.rotation_std_rad is not None:
            uncertainties.append(UncertaintyEstimate(
                "rotation_vector_std", observation.target_object_id, "gongshu_adapter_v0.1",
                observation.rotation_std_rad, UncertaintyKind.PROXY, "rad",
                evidence_ids=(observation.observation_id,),
            ))

        belief = RobotBeliefState(
            episode_id=observation.episode_id,
            revision=observation.revision,
            timestamp=observation.timestamp_s,
            objects=objects,
            grasp_candidates=tuple(candidates),
            uncertainties=tuple(uncertainties),
            evidence_ids=(observation.observation_id,),
            robot_state=observation.robot_state,
            task_data={
                "action_counts": observation.action_counts,
                "quality": observation.quality,
                "occlusion": observation.occlusion,
                "needs_recovery": observation.needs_recovery,
                "pending_grasp_verification": observation.pending_grasp_verification,
            },
        )
        context = EpisodeContext(
            "gongshu_xiezhi",
            observation.episode_id,
            TaskSpec("gongshu_decision", {"target_object_id": observation.target_object_id}),
            0,
        )
        skills = tuple(SkillSpec(name, f"Gongshu {name} capability") for name in self._SKILLS)
        decision = self._policy.decide(
            context,
            belief,
            MemorySnapshot(observation.episode_id, (), observation.revision),
            skills,
            DecisionContext(
                observation.revision,
                observation.remaining_steps,
                0.0,
                None,
            ),
        )
        if decision.action is None:
            return GongshuDecision(
                None,
                None,
                stop_reason=decision.stop_reason,
                diagnostics=to_jsonable(decision.diagnostics),
            )
        parameters = to_jsonable(decision.action.parameters)
        return GongshuDecision(
            decision.action.action_id,
            decision.action.skill_name,
            candidate_id=parameters.get("candidate_id"),
            parameters=parameters,
            diagnostics=to_jsonable(decision.diagnostics),
        )
