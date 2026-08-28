from __future__ import annotations

import unittest
from pathlib import Path

from vision2grasp.control import PandaOSCGraspExecutor
from vision2grasp.evaluation import RobosuiteBottleLiftEvaluator
from vision2grasp.geometry import MaskDepthTargetLocalizer
from vision2grasp.grasp import PCATopGraspPlanner
from vision2grasp.perception import UltralyticsYOLOSegmenter
from vision2grasp.pipeline import PipelinePhase, Vision2GraspPipeline
from vision2grasp.simulation import RobosuiteRGBDSimulator, RobosuiteSimulationConfig


ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "artifacts" / "models" / "yolo11n-seg.pt"


@unittest.skipUnless(
    WEIGHTS.is_file(),
    "official YOLO weights are required for the end-to-end pipeline integration test",
)
class BottlePipelineIntegrationTests(unittest.TestCase):
    def test_seeded_bottle_scene_completes_and_lifts_without_truth_feedback(self) -> None:
        simulator = RobosuiteRGBDSimulator(
            RobosuiteSimulationConfig(
                environment="BottleLift",
                camera_name="frontview",
                camera_width=640,
                camera_height=480,
                horizon=500,
                seed=7,
            )
        )
        try:
            simulator.reset(seed=7)
            evaluator = RobosuiteBottleLiftEvaluator(simulator)
            evaluator.begin_episode()
            pipeline = Vision2GraspPipeline(
                simulator,
                UltralyticsYOLOSegmenter(),
                MaskDepthTargetLocalizer(),
                PCATopGraspPlanner(),
                PandaOSCGraspExecutor(simulator),
            )

            run = pipeline.run()
            evaluation = evaluator.finish_episode(motion_completed=run.success)

            self.assertTrue(run.success, run.message)
            self.assertEqual(run.final_phase, PipelinePhase.SUCCEEDED)
            self.assertEqual(
                run.selected_detection.class_name,  # type: ignore[union-attr]
                "bottle",
            )
            self.assertGreaterEqual(
                run.selected_detection.confidence,  # type: ignore[union-attr]
                0.50,
            )
            self.assertEqual(
                run.selected_candidate.score_terms[  # type: ignore[union-attr]
                    "axisymmetric_circle_fit"
                ],
                1.0,
            )
            self.assertTrue(run.execution.success)  # type: ignore[union-attr]
            self.assertTrue(evaluation.success)
            self.assertGreaterEqual(evaluation.vertical_displacement_m, 0.03)
            self.assertFalse(hasattr(simulator, "object_pose"))
        finally:
            simulator.close()


if __name__ == "__main__":
    unittest.main()
