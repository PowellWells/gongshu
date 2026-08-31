"""Local-only successful timing history for honest Spatial ETA estimates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics
import threading
from typing import Iterable


TIMING_HISTORY_SCHEMA_VERSION = "vision2grasp.spatial-timing-history/v1"
TIMING_HISTORY_ENV = "VISION2GRASP_SPATIAL_TIMING_HISTORY"
MAX_RECENT_SUCCESSFUL_SAMPLES = 25


def default_timing_history_path() -> Path:
    override = os.environ.get(TIMING_HISTORY_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "Vision2Grasp" / "spatial-timings.json"
    return Path.home() / ".cache" / "vision2grasp" / "spatial-timings.json"


@dataclass(frozen=True, slots=True)
class TimingProfile:
    model: str
    compute_device: str
    input_size: int
    cold_start: bool

    def key(self, stage: str) -> str:
        start = "cold" if self.cold_start else "warm"
        return f"{self.model}|{self.compute_device}|{self.input_size}|{start}|{stage}"


class SpatialTimingHistory:
    def __init__(
        self,
        path: Path | None = None,
        *,
        benchmark_path: Path | None = None,
        persistent: bool = True,
    ) -> None:
        self.path = Path(path or default_timing_history_path())
        self._persistent = persistent
        self._lock = threading.RLock()
        self._samples: dict[str, list[float]] = {}
        self._load()
        if benchmark_path is not None:
            self.seed_from_benchmark(Path(benchmark_path))

    def add_success(
        self,
        profile: TimingProfile,
        stage_durations: dict[str, float],
        total_s: float,
    ) -> None:
        with self._lock:
            for stage, duration in stage_durations.items():
                self._append(profile.key(stage), duration)
            self._append(profile.key("TOTAL"), total_s)
            self._save()

    def estimate(
        self,
        profile: TimingProfile,
        *,
        stage: str,
        stage_elapsed_s: float,
        total_elapsed_s: float,
    ) -> dict[str, object]:
        with self._lock:
            stage_samples = tuple(self._samples.get(profile.key(stage), ()))
            total_samples = tuple(self._samples.get(profile.key("TOTAL"), ()))
        stage_median = self._median(stage_samples)
        total_median = self._median(total_samples)
        available = stage_median is not None or total_median is not None
        result: dict[str, object] = {
            "available": available,
            "source": "LOCAL_SUCCESS_HISTORY" if available else "ESTIMATING",
            "stage": stage,
            "profile": {
                "compute_device": profile.compute_device,
                "input_size": profile.input_size,
                "start_type": "COLD_START" if profile.cold_start else "WARM_START",
            },
            "stage_sample_count": len(stage_samples),
            "total_sample_count": len(total_samples),
            "stage_median_s": stage_median,
            "total_median_s": total_median,
            "stage_remaining_s": (
                None
                if stage_median is None
                else max(stage_median - stage_elapsed_s, 0.0)
            ),
            "estimated_remaining_s": (
                None
                if total_median is None
                else max(total_median - total_elapsed_s, 0.0)
            ),
        }
        typical = self._typical_range(stage_samples)
        if typical is not None:
            result["stage_typical_range_s"] = list(typical)
        return result

    def seed_from_benchmark(self, benchmark_path: Path) -> None:
        if not benchmark_path.is_file():
            return
        try:
            document = json.loads(benchmark_path.read_text(encoding="utf-8"))
            input_size = int(document["input_size"]["width"])
            cold = TimingProfile(
                "depth-anything-v2-metric-indoor-small", "cpu", input_size, True
            )
            warm = TimingProfile(
                "depth-anything-v2-metric-indoor-small", "cpu", input_size, False
            )
            seeds: dict[str, Iterable[float]] = {
                cold.key("MODEL_LOADING"): [float(document["first_model_load_s"])],
                cold.key("DEPTH_INFERENCE"): [
                    float(document["first_depth_inference_s"])
                ],
                cold.key("TOTAL"): [float(document["first_spatial_end_to_end_s"])],
                warm.key("DEPTH_INFERENCE"): [
                    float(value) for value in document["stable_depth_inference_s"]
                ],
                warm.key("TOTAL"): [
                    float(value) for value in document["stable_spatial_end_to_end_s"]
                ],
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return
        changed = False
        with self._lock:
            for key, values in seeds.items():
                if key in self._samples:
                    continue
                clean = [value for value in values if math.isfinite(value) and value >= 0.0]
                if clean:
                    self._samples[key] = clean[-MAX_RECENT_SUCCESSFUL_SAMPLES:]
                    changed = True
            if changed:
                self._save()

    def _append(self, key: str, value: float) -> None:
        if not math.isfinite(value) or value < 0.0:
            return
        samples = self._samples.setdefault(key, [])
        samples.append(float(value))
        del samples[:-MAX_RECENT_SUCCESSFUL_SAMPLES]

    def _load(self) -> None:
        if not self._persistent:
            return
        if not self.path.is_file():
            return
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document.get("schema_version") != TIMING_HISTORY_SCHEMA_VERSION:
                return
            raw = document.get("samples")
            if not isinstance(raw, dict):
                return
            for key, values in raw.items():
                if not isinstance(key, str) or not isinstance(values, list):
                    continue
                clean = [
                    float(value)
                    for value in values
                    if isinstance(value, (int, float))
                    and math.isfinite(float(value))
                    and float(value) >= 0.0
                ]
                if clean:
                    self._samples[key] = clean[-MAX_RECENT_SUCCESSFUL_SAMPLES:]
        except (OSError, ValueError, json.JSONDecodeError):
            return

    def _save(self) -> None:
        if not self._persistent:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "schema_version": TIMING_HISTORY_SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "samples": self._samples,
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _median(values: tuple[float, ...]) -> float | None:
        return None if not values else float(statistics.median(values))

    @staticmethod
    def _typical_range(values: tuple[float, ...]) -> tuple[float, float] | None:
        if len(values) < 3:
            return None
        median = statistics.median(values)
        mad = statistics.median(abs(value - median) for value in values)
        radius = 3.0 * 1.4826 * mad
        return max(float(median - radius), 0.0), float(median + radius)
