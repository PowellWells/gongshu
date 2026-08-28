from __future__ import annotations

import unittest

import numpy as np

from vision2grasp.evaluation import (
    BottleLiftEvaluationConfig,
    RobosuiteBottleLiftEvaluator,
)


class FakeTruthSource:
    def __init__(self) -> None:
        self.height_m = 0.88

    def _evaluation_object_pose(self, object_name: str) -> np.ndarray:
        if object_name != "bottle":
            raise ValueError(object_name)
        pose = np.eye(4, dtype=np.float64)
        pose[:3, 3] = [0.01, -0.02, self.height_m]
        return pose


class BottleLiftEvaluatorTests(unittest.TestCase):
    def test_success_requires_motion_completion_and_vertical_lift(self) -> None:
        source = FakeTruthSource()
        evaluator = RobosuiteBottleLiftEvaluator(source)
        evaluator.begin_episode()
        source.height_m += 0.05

        result = evaluator.finish_episode(motion_completed=True)

        self.assertTrue(result.success)
        self.assertAlmostEqual(result.vertical_displacement_m, 0.05)
        self.assertAlmostEqual(result.total_displacement_m, 0.05)

    def test_motion_failure_cannot_be_evaluated_as_success(self) -> None:
        source = FakeTruthSource()
        evaluator = RobosuiteBottleLiftEvaluator(source)
        evaluator.begin_episode()
        source.height_m += 0.05

        result = evaluator.finish_episode(motion_completed=False)

        self.assertFalse(result.success)
        with self.assertRaisesRegex(RuntimeError, "begin_episode"):
            evaluator.finish_episode(motion_completed=True)

    def test_rejects_invalid_threshold(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            BottleLiftEvaluationConfig(minimum_vertical_displacement_m=0.0)


if __name__ == "__main__":
    unittest.main()
