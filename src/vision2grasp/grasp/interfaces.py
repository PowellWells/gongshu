"""Interfaces for PCA-based grasp candidate generation."""

from typing import Protocol, Sequence

from vision2grasp.contracts import GraspCandidate, LocalizedTarget


class GraspPlanner(Protocol):
    def plan(self, target: LocalizedTarget) -> Sequence[GraspCandidate]: ...
