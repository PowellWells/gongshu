"""Interfaces for evaluation metrics."""

from typing import Mapping, Protocol

from vision2grasp.contracts import LocalizedTarget

from .ground_truth import GroundTruthObjectPose


class LocalizationEvaluator(Protocol):
    def evaluate(
        self,
        prediction: LocalizedTarget,
        truth: GroundTruthObjectPose,
    ) -> Mapping[str, float]: ...
