"""Gongshu-owned contracts at the optional Xiezhi extension boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
import re
from types import MappingProxyType
from typing import Any, Protocol

from vision2grasp.contracts import GraspCandidate


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypeError("mapping values must use string keys")
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class GongshuObservation:
    """Decision-ready Gongshu evidence; no simulator truth or driver objects."""

    episode_id: str
    observation_id: str
    revision: int
    timestamp_s: float
    target_object_id: str
    candidates: tuple[GraspCandidate, ...] = ()
    position_std_m: float | None = None
    rotation_std_rad: float | None = None
    quality: float | None = None
    occlusion: float | None = None
    remaining_steps: int = 12
    action_counts: Mapping[str, int] = field(default_factory=dict)
    robot_state: Mapping[str, Any] = field(default_factory=dict)
    needs_recovery: bool = False
    pending_grasp_verification: bool = False

    def __post_init__(self) -> None:
        for name in ("episode_id", "observation_id", "target_object_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("revision must be a nonnegative integer")
        if not isfinite(self.timestamp_s) or self.timestamp_s < 0:
            raise ValueError("timestamp_s must be finite and nonnegative")
        candidates = tuple(self.candidates)
        if any(not isinstance(candidate, GraspCandidate) for candidate in candidates):
            raise TypeError("candidates must contain Gongshu GraspCandidate values")
        if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise ValueError("candidate IDs must be unique")
        object.__setattr__(self, "candidates", candidates)
        for name in ("position_std_m", "rotation_std_rad"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and nonnegative")
        for name in ("quality", "occlusion"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{name} must be within [0, 1]")
        if type(self.remaining_steps) is not int or self.remaining_steps < 1:
            raise ValueError("remaining_steps must be a positive integer")
        if any(type(count) is not int or count < 0 for count in self.action_counts.values()):
            raise ValueError("action counts must be nonnegative integers")
        object.__setattr__(self, "action_counts", _freeze_mapping(self.action_counts))
        object.__setattr__(self, "robot_state", _freeze_mapping(self.robot_state))


@dataclass(frozen=True, slots=True)
class GongshuDecision:
    """Platform-neutral Xiezhi decision translated for Gongshu execution."""

    action_id: str | None
    action_name: str | None
    candidate_id: str | None = None
    stop_reason: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        has_action = self.action_id is not None or self.action_name is not None
        if has_action and (not self.action_id or not self.action_name):
            raise ValueError("action_id and action_name must be provided together")
        if not has_action and not self.stop_reason:
            raise ValueError("a decision needs an action or stop_reason")
        object.__setattr__(self, "parameters", _freeze_mapping(self.parameters))
        object.__setattr__(self, "diagnostics", _freeze_mapping(self.diagnostics))


class XiezhiDecisionBackend(Protocol):
    def decide(self, observation: GongshuObservation) -> GongshuDecision: ...


@dataclass(frozen=True, slots=True)
class XiezhiAdapterConfig:
    enabled: bool = False
    algorithm: str = "rule_based"

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("enabled must be bool")
        if not isinstance(self.algorithm, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}", self.algorithm
        ):
            raise ValueError("algorithm must be a lowercase identifier")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "XiezhiAdapterConfig":
        values = dict(value or {})
        unknown = values.keys() - {"enabled", "algorithm"}
        if unknown:
            raise ValueError(f"Unknown Xiezhi adapter settings: {', '.join(sorted(unknown))}")
        return cls(**values)


@dataclass(frozen=True, slots=True)
class IntegrationResult:
    xiezhi_enabled: bool
    mode: str
    decision: GongshuDecision | None
    execution: Any

    def __post_init__(self) -> None:
        expected = "xiezhi" if self.xiezhi_enabled else "gongshu_legacy"
        if self.mode != expected:
            raise ValueError(f"mode must be {expected}")
