"""Measure the frozen v0.5 CPU spatial chain with an exact 518 x 518 input."""

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

from vision2grasp.contracts import RGBFrame
from vision2grasp.spatial_perception import (
    CalibratedCameraIntrinsicsProvider,
    MaskSpatialPerceptionProvider,
    MonocularDepthConfig,
    MonocularDepthProvider,
    NominalFOVCameraIntrinsicsProvider,
    PriorityCameraIntrinsicsProvider,
    SpatialPerceptionService,
)
from vision2grasp.target_perception import TargetInstance, TargetSceneSnapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_snapshot(rgb: np.ndarray, run_index: int) -> TargetSceneSnapshot:
    height, width = rgb.shape[:2]
    mask_u8 = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(
        mask_u8,
        (width // 2, height // 2),
        (width // 5, height // 4),
        0.0,
        0.0,
        360.0,
        1,
        -1,
    )
    mask = mask_u8.astype(np.bool_)
    rows, columns = np.nonzero(mask)
    timestamp_s = 1000.0 + run_index
    frame = RGBFrame(run_index, timestamp_s, "cpu-benchmark", rgb)
    return TargetSceneSnapshot(
        snapshot_id=f"benchmark-snapshot-{run_index}",
        frame=frame,
        target=TargetInstance(
            instance_id=f"benchmark-target-{run_index}",
            mask=mask,
            bbox_xyxy=(
                float(columns.min()),
                float(rows.min()),
                float(columns.max() + 1),
                float(rows.max() + 1),
            ),
            centroid_2d=(float(columns.mean()), float(rows.mean())),
            source_frame_id=frame.frame_id,
            source_timestamp_s=frame.timestamp_s,
        ),
    )


def analyze(service: SpatialPerceptionService, snapshot: TargetSceneSnapshot) -> dict[str, object]:
    state = service.analyze(
        snapshot,
        expected_snapshot_id=snapshot.snapshot_id,
        expected_source_frame_id=snapshot.frame.frame_id,
        expected_target_instance_id=snapshot.target.instance_id,
        expected_source_timestamp_s=snapshot.frame.timestamp_s,
    )
    if state["status"] != "READY":
        raise RuntimeError(f"spatial benchmark failed: {state}")
    return state


def run_benchmark(image_path: Path, stable_runs: int) -> dict[str, object]:
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        raise FileNotFoundError(f"benchmark image could not be read: {image_path}")
    bgr = cv2.resize(bgr, (518, 518), interpolation=cv2.INTER_AREA)
    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    provider = MaskSpatialPerceptionProvider(
        MonocularDepthProvider(MonocularDepthConfig(input_size=518)),
        PriorityCameraIntrinsicsProvider(
            (
                CalibratedCameraIntrinsicsProvider(),
                NominalFOVCameraIntrinsicsProvider(),
            )
        ),
    )
    service = SpatialPerceptionService(provider)

    first = analyze(service, make_snapshot(rgb, 1))
    stable_states = [
        analyze(service, make_snapshot(rgb, index + 2))
        for index in range(stable_runs)
    ]
    stable_inference = [float(state["timing"]["depth_inference_s"]) for state in stable_states]
    stable_total = [float(state["timing"]["total_s"]) for state in stable_states]
    return {
        "schema_version": "vision2grasp.spatial-benchmark/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "input_size": {"width": 518, "height": 518},
        "stable_runs": stable_runs,
        "first_model_load_s": first["timing"]["model_load_s"],
        "first_depth_inference_s": first["timing"]["depth_inference_s"],
        "first_spatial_end_to_end_s": first["timing"]["total_s"],
        "stable_depth_inference_s": stable_inference,
        "stable_depth_inference_median_s": statistics.median(stable_inference),
        "stable_spatial_end_to_end_s": stable_total,
        "stable_spatial_end_to_end_median_s": statistics.median(stable_total),
        "first_model_location": first["timing"].get("model_location"),
        "depth_mode": first["observation"]["depth_mode"],
        "intrinsics_source": first["observation"]["intrinsics_source"],
        "calibration_state": first["observation"]["calibration_state"],
        "geometry_sanity": first["observation"]["geometry_sanity"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "perception" / "bottle_cc0.jpg",
    )
    parser.add_argument("--stable-runs", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "benchmarks" / "spatial-v0.5-cpu.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.stable_runs <= 0:
        raise ValueError("stable-runs must be positive")
    started = time.perf_counter()
    result = run_benchmark(args.image, args.stable_runs)
    result["benchmark_wall_time_s"] = time.perf_counter() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
