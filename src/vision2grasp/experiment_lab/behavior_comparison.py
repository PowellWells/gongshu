"""Experiment Lab projections over Gongshu-owned runtime behavior records."""

from __future__ import annotations

from collections import defaultdict
from math import dist
from typing import Iterable

from vision2grasp.simulation import BehaviorRecord


BEHAVIOR_COMPARISON_SCHEMA_VERSION = "gongshu.behavior-comparison/v1"


def _path_length(record: BehaviorRecord) -> float:
    positions = [point.position_world for point in record.trajectory_points]
    return sum(dist(left, right) for left, right in zip(positions, positions[1:]))


def build_behavior_comparison(
    records: Iterable[BehaviorRecord],
) -> dict[str, object]:
    """Return the latest same-scene pair produced by different algorithms."""

    ordered = tuple(records)
    groups: dict[tuple[str, str], list[BehaviorRecord]] = defaultdict(list)
    scene_order: list[tuple[str, str]] = []
    for record in ordered:
        key = (record.scene_id, record.target_id)
        groups[key].append(record)
        if key in scene_order:
            scene_order.remove(key)
        scene_order.append(key)

    pair: tuple[BehaviorRecord, BehaviorRecord] | None = None
    for key in reversed(scene_order):
        group = groups[key]
        latest_by_algorithm: dict[str, BehaviorRecord] = {}
        for record in reversed(group):
            latest_by_algorithm.setdefault(record.algorithm_id, record)
        if len(latest_by_algorithm) < 2:
            continue
        candidates = list(latest_by_algorithm.values())
        left = next(
            (record for record in candidates if record.provider_id == "xiezhi"),
            candidates[0],
        )
        right = next(
            record for record in candidates if record.algorithm_id != left.algorithm_id
        )
        pair = (left, right)
        break

    if pair is None:
        return {
            "schema_version": BEHAVIOR_COMPARISON_SCHEMA_VERSION,
            "status": "WAITING_FOR_PAIR",
            "record_count": len(ordered),
            "scene_id": None,
            "target_id": None,
            "left": None,
            "right": None,
            "trajectory_difference": None,
        }

    left, right = pair
    left_length = _path_length(left)
    right_length = _path_length(right)
    return {
        "schema_version": BEHAVIOR_COMPARISON_SCHEMA_VERSION,
        "status": "READY",
        "record_count": len(ordered),
        "scene_id": left.scene_id,
        "target_id": left.target_id,
        "left": left.public_metadata(),
        "right": right.public_metadata(),
        "trajectory_difference": {
            "same_start": dist(left.start_pose, right.start_pose) <= 1e-6,
            "endpoint_distance_m": dist(left.target_pose, right.target_pose),
            "left_path_length_m": left_length,
            "right_path_length_m": right_length,
            "path_length_difference_m": abs(left_length - right_length),
            "selected_candidate_changed": (
                left.selected_candidate_id != right.selected_candidate_id
            ),
        },
    }


__all__ = [
    "BEHAVIOR_COMPARISON_SCHEMA_VERSION",
    "build_behavior_comparison",
]
