"""Run the seeded BottleLift perception-to-grasp demo and print JSON."""

from __future__ import annotations

import json

from vision2grasp.control import PandaOSCGraspExecutor
from vision2grasp.evaluation import RobosuiteBottleLiftEvaluator
from vision2grasp.geometry import MaskDepthTargetLocalizer
from vision2grasp.grasp import PCATopGraspPlanner
from vision2grasp.perception import UltralyticsYOLOSegmenter
from vision2grasp.pipeline import Vision2GraspPipeline
from vision2grasp.simulation import RobosuiteRGBDSimulator, RobosuiteSimulationConfig


def main() -> int:
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
        run = Vision2GraspPipeline(
            simulator,
            UltralyticsYOLOSegmenter(),
            MaskDepthTargetLocalizer(),
            PCATopGraspPlanner(),
            PandaOSCGraspExecutor(simulator),
        ).run()
        evaluation = evaluator.finish_episode(motion_completed=run.success)

        detection = run.selected_detection
        target = run.localized_target
        candidate = run.selected_candidate
        execution = run.execution
        summary = {
            "pipeline_success": run.success,
            "pipeline_final_phase": run.final_phase.value,
            "pipeline_message": run.message,
            "pipeline_phases": [phase.value for phase in run.visited_phases],
            "detection": (
                None
                if detection is None
                else {
                    "class_name": detection.class_name,
                    "confidence": detection.confidence,
                    "mask_pixels": int(detection.mask.sum()),
                }
            ),
            "localized_target": (
                None
                if target is None
                else {
                    "centroid_world_m": target.centroid_world_m.tolist(),
                    "point_count": int(target.points_world_m.shape[0]),
                    "depth_valid_ratio": target.depth_valid_ratio,
                }
            ),
            "candidate": (
                None
                if candidate is None
                else {
                    "candidate_id": candidate.candidate_id,
                    "position_world_m": candidate.world_from_grasp[:3, 3].tolist(),
                    "gripper_width_m": candidate.gripper_width_m,
                    "score": candidate.score,
                    "reachable": candidate.reachable,
                }
            ),
            "execution": (
                None
                if execution is None
                else {
                    "success": execution.success,
                    "phases": [phase.value for phase in execution.visited_phases],
                    "message": execution.message,
                }
            ),
            "evaluation": {
                "success": evaluation.success,
                "vertical_displacement_m": evaluation.vertical_displacement_m,
                "total_displacement_m": evaluation.total_displacement_m,
                "minimum_vertical_displacement_m": (
                    evaluation.minimum_vertical_displacement_m
                ),
            },
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if evaluation.success else 1
    finally:
        simulator.close()


if __name__ == "__main__":
    raise SystemExit(main())
