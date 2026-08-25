"""Interfaces for deterministic Panda grasp execution."""

from typing import Protocol

from vision2grasp.contracts import ExecutionResult, GraspCandidate


class GraspExecutor(Protocol):
    def execute(self, candidate: GraspCandidate) -> ExecutionResult: ...
