"""Benchmark the official v0.6 GR-ConvNet Top-K chain on the frozen CC0 bottle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import statistics
import time

import cv2
import numpy as np
import torch

from vision2grasp.contracts import RGBFrame
from vision2grasp.grasp_planning import (
    GRCONVNET_MODEL_ASSET,
    GRConvNetDetector,
    GRConvNetDetectorConfig,
    PixelWiseTopKGraspPlanner,
    TopKGraspPlannerConfig,
)
from vision2grasp.spatial_perception import (
    MaskSpatialPerceptionProvider,
    MonocularDepthProvider,
    NominalFOVCameraIntrinsicsProvider,
)
from vision2grasp.target_perception import (
    FastSAMTargetSegmenter,
    FastSAMTargetSegmenterConfig,
    TargetPerceptionService,
    TargetSceneSnapshot,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_snapshot(rgb: np.ndarray) -> TargetSceneSnapshot:
    frame = RGBFrame(600, 600.0, "grasp-v06-benchmark", rgb)
    service = TargetPerceptionService(
        FastSAMTargetSegmenter(FastSAMTargetSegmenterConfig(allow_download=False))
    )
    analyzed = service.analyze(frame)
    candidates = analyzed["candidates"]
    if not candidates:
        raise RuntimeError("FastSAM produced no target candidate for benchmark image")
    service.select(str(candidates[0]["id"]), source_frame_id=frame.frame_id)
    snapshot = service.selected_scene_snapshot()
    if snapshot is None:
        raise RuntimeError("target selection did not produce a scene snapshot")
    return snapshot


def run_benchmark(image_path: Path, stable_runs: int, device: str) -> dict[str, object]:
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        raise FileNotFoundError(f"benchmark image could not be read: {image_path}")
    bgr = cv2.resize(bgr, (518, 518), interpolation=cv2.INTER_AREA)
    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    target_started = time.perf_counter()
    snapshot = make_snapshot(rgb)
    target_elapsed = time.perf_counter() - target_started

    spatial_started = time.perf_counter()
    observation = MaskSpatialPerceptionProvider(
        MonocularDepthProvider(),
        NominalFOVCameraIntrinsicsProvider(),
    ).analyze(snapshot)
    spatial_elapsed = time.perf_counter() - spatial_started

    detector = GRConvNetDetector(GRConvNetDetectorConfig(device=device))
    planner = PixelWiseTopKGraspPlanner(detector, TopKGraspPlannerConfig())
    cold = planner.plan(observation, snapshot)
    stable = [planner.plan(observation, snapshot) for _ in range(stable_runs)]
    stable_inference = [item.maps.inference_time_s for item in stable]
    stable_total = [item.planning_time_s for item in stable]
    representative = stable[-1]
    return {
        "schema_version": "vision2grasp.grasp-benchmark/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "device": representative.maps.compute_device,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "input_image": str(image_path),
        "input_size": {"width": 518, "height": 518},
        "model_revision": GRCONVNET_MODEL_ASSET.revision,
        "model_sha256": GRCONVNET_MODEL_ASSET.sha256,
        "model_license": GRCONVNET_MODEL_ASSET.license,
        "target_perception_s": target_elapsed,
        "target_mask_pixels": int(np.count_nonzero(snapshot.target.mask)),
        "spatial_preparation_s": spatial_elapsed,
        "spatial_depth_mode": observation.depth_mode.value,
        "cold_model_load_s": cold.maps.model_load_time_s,
        "cold_inference_s": cold.maps.inference_time_s,
        "cold_planning_total_s": cold.planning_time_s,
        "stable_runs": stable_runs,
        "stable_inference_s": stable_inference,
        "stable_inference_median_s": statistics.median(stable_inference),
        "stable_planning_total_s": stable_total,
        "stable_planning_total_median_s": statistics.median(stable_total),
        "planning_status": (
            representative.plan.planning_state.value
            if representative.plan is not None
            else "PLANNING_REJECTED"
        ),
        "rejection_reason": representative.rejection_reason,
        "candidate_count": len(representative.candidates),
        "executable_count": sum(item.executable for item in representative.candidates),
        "best_candidate_id": (
            representative.plan.best_candidate_id if representative.plan is not None else None
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "perception" / "bottle_cc0.jpg",
    )
    parser.add_argument("--stable-runs", type=int, default=5)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "benchmarks" / "grasp-v0.6-auto.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.stable_runs <= 0:
        raise ValueError("stable-runs must be positive")
    result = run_benchmark(args.image, args.stable_runs, args.device)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
