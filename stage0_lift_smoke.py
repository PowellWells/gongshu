"""Minimal Vision2Grasp stage-0 environment and sensor smoke test."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "wgl")

import cv2
import numpy as np
import robosuite as suite
import robosuite.macros as macros
from robosuite.controllers.composite.composite_controller_factory import (
    refactor_composite_controller_config,
)
from robosuite.utils.camera_utils import get_real_depth_map


OUTPUT_DIR = Path(__file__).resolve().parent / "artifacts" / "stage0"
CAMERA_NAME = "agentview"
HEIGHT = 480
WIDTH = 640


def save_rgb_and_depth(rgb: np.ndarray, depth_m: np.ndarray) -> dict[str, float]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cv2.imwrite(str(OUTPUT_DIR / "rgb.png"), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))

    finite = np.isfinite(depth_m) & (depth_m > 0)
    if not np.any(finite):
        raise RuntimeError("Metric depth map contains no finite positive samples.")

    valid = depth_m[finite]
    low, high = np.percentile(valid, [2, 98])
    scaled = np.clip((depth_m - low) / max(high - low, 1e-6), 0.0, 1.0)
    heatmap = cv2.applyColorMap((255 * (1.0 - scaled)).astype(np.uint8), cv2.COLORMAP_TURBO)
    cv2.imwrite(str(OUTPUT_DIR / "depth_heatmap.png"), heatmap)

    depth_mm = np.clip(depth_m * 1000.0, 0, np.iinfo(np.uint16).max).astype(np.uint16)
    cv2.imwrite(str(OUTPUT_DIR / "depth_metric_mm.png"), depth_mm)

    return {
        "depth_min_m": float(valid.min()),
        "depth_median_m": float(np.median(valid)),
        "depth_max_m": float(valid.max()),
        "depth_valid_ratio": float(finite.mean()),
    }


def main() -> None:
    macros.IMAGE_CONVENTION = "opencv"

    arm_config = suite.load_part_controller_config(default_controller="OSC_POSE")
    controller_config = refactor_composite_controller_config(
        arm_config,
        robot_type="Panda",
        arms=["right"],
    )

    env = suite.make(
        env_name="Lift",
        robots="Panda",
        controller_configs=controller_config,
        has_renderer=False,
        has_offscreen_renderer=True,
        use_camera_obs=True,
        camera_names=CAMERA_NAME,
        camera_heights=HEIGHT,
        camera_widths=WIDTH,
        camera_depths=True,
        camera_segmentations=None,
        control_freq=20,
        horizon=300,
        ignore_done=True,
        hard_reset=False,
    )

    try:
        observation = env.reset()
        rgb_key = f"{CAMERA_NAME}_image"
        depth_key = f"{CAMERA_NAME}_depth"
        if rgb_key not in observation or depth_key not in observation:
            raise KeyError(f"Missing RGB-D observations. Available keys: {sorted(observation)}")

        rgb = np.asarray(observation[rgb_key])
        normalized_depth = np.asarray(observation[depth_key]).squeeze()
        metric_depth = get_real_depth_map(env.sim, normalized_depth)
        depth_stats = save_rgb_and_depth(rgb, metric_depth)

        eef_key = "robot0_eef_pos"
        gripper_key = "robot0_gripper_qpos"
        initial_eef = np.asarray(observation[eef_key], dtype=float).copy()
        initial_gripper = np.asarray(observation[gripper_key], dtype=float).copy()

        action = np.zeros(env.action_dim, dtype=float)
        action[-1] = -1.0
        for _ in range(10):
            observation, _, _, _ = env.step(action)

        action[:] = 0.0
        action[2] = 0.10
        action[-1] = -1.0
        for _ in range(20):
            observation, _, _, _ = env.step(action)

        action[:] = 0.0
        action[-1] = -1.0
        for _ in range(20):
            observation, _, _, _ = env.step(action)
        moved_eef = np.asarray(observation[eef_key], dtype=float).copy()

        action[:] = 0.0
        action[-1] = 1.0
        for _ in range(30):
            observation, _, _, _ = env.step(action)
        closed_gripper = np.asarray(observation[gripper_key], dtype=float).copy()

        eef_displacement = float(np.linalg.norm(moved_eef - initial_eef))
        gripper_displacement = float(np.linalg.norm(closed_gripper - initial_gripper))
        if eef_displacement < 0.01:
            raise RuntimeError(f"OSC_POSE motion too small: {eef_displacement:.6f} m")
        if gripper_displacement < 0.005:
            raise RuntimeError(f"Gripper motion too small: {gripper_displacement:.6f} rad")

        report = {
            "environment": "Lift",
            "robot": "Panda",
            "controller": "OSC_POSE",
            "action_dim": int(env.action_dim),
            "rgb_shape": list(rgb.shape),
            "depth_shape": list(metric_depth.shape),
            "eef_initial_m": initial_eef.tolist(),
            "eef_after_motion_m": moved_eef.tolist(),
            "eef_displacement_m": eef_displacement,
            "gripper_initial": initial_gripper.tolist(),
            "gripper_closed": closed_gripper.tolist(),
            "gripper_displacement": gripper_displacement,
            **depth_stats,
            "status": "PASS",
        }
        (OUTPUT_DIR / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
    finally:
        env.close()


if __name__ == "__main__":
    main()
