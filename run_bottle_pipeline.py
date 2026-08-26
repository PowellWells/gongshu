"""Run the seeded BottleLift demo and export public frontend artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from vision2grasp.control import PandaOSCGraspExecutor
from vision2grasp.evaluation import RobosuiteBottleLiftEvaluator
from vision2grasp.geometry import MaskDepthTargetLocalizer
from vision2grasp.grasp import PCATopGraspPlanner
from vision2grasp.perception import UltralyticsYOLOSegmenter
from vision2grasp.pipeline import Vision2GraspPipeline
from vision2grasp.simulation import RobosuiteRGBDSimulator, RobosuiteSimulationConfig
from vision2grasp.visualization import RunArtifactExporter, make_run_id


PROJECT_ROOT = Path(__file__).resolve().parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic bottle grasp and export run.json v1."
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "runs",
        help="Parent directory for immutable run folders.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional filesystem-safe run id; generated automatically by default.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
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
        final_frame = simulator.capture()
        exported = RunArtifactExporter().export(
            run,
            output_root=args.output_root,
            run_id=args.run_id or make_run_id("bottle-lift-seed7"),
            final_frame=final_frame,
        )
        print(json.dumps(exported.document, ensure_ascii=False, indent=2))
        print(f"run.json: {exported.run_json_path}", file=sys.stderr)
        return 0 if evaluation.success else 1
    finally:
        simulator.close()


if __name__ == "__main__":
    raise SystemExit(main())
