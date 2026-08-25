"""Public data contracts for the Vision2Grasp pipeline."""

from .contracts import (
    CameraIntrinsics,
    Detection2D,
    ExecutionPhase,
    ExecutionResult,
    GraspCandidate,
    LocalizedTarget,
    PandaProprioception,
    RGBDFrame,
)

__all__ = [
    "CameraIntrinsics",
    "Detection2D",
    "ExecutionPhase",
    "ExecutionResult",
    "GraspCandidate",
    "LocalizedTarget",
    "PandaProprioception",
    "RGBDFrame",
]

__version__ = "0.1.0"
