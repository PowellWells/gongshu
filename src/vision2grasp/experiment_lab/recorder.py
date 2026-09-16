"""Experiment Lab trial records for Gongshu local-image runs."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any

from vision2grasp.intelligence import AlgorithmDecision
from vision2grasp.sources.local_image import LocalImageObservation


EXPERIMENT_TRIAL_SCHEMA_VERSION = "gongshu.experiment-trial/v1"


class ExperimentTrialRecorder:
    """Persist experiment evidence without owning scenes, algorithms, or runtime."""

    def __init__(self, records_root: Path) -> None:
        self._records_root = Path(records_root).resolve()
        self._lock = threading.RLock()

    def start(self, observation: LocalImageObservation) -> None:
        record = {
            "schema_version": EXPERIMENT_TRIAL_SCHEMA_VERSION,
            "trial_id": observation.run_id,
            "status": "OBSERVATION_READY",
            "input": observation.as_dict(),
            "algorithm": None,
            "decision": None,
            "mujoco_result": None,
        }
        self._write(observation.run_id, record)

    def record_decision(self, run_id: str, decision: AlgorithmDecision) -> None:
        with self._lock:
            record = self._read(run_id)
            metadata = decision.public_metadata()
            record["algorithm"] = {
                "provider": metadata["provider"],
                "algorithm": metadata["algorithm"],
                "used_fallback": metadata["used_fallback"],
            }
            record["decision"] = metadata
            record["status"] = "DECISION_RECORDED"
            self._write(run_id, record)

    def record_result(self, run_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            record = self._read(run_id)
            record["mujoco_result"] = dict(result)
            record["status"] = "COMPLETED"
            self._write(run_id, record)

    def _path(self, run_id: str) -> Path:
        if not run_id.startswith("offline-") or any(part in run_id for part in ("/", "\\", "..")):
            raise ValueError("invalid offline trial identifier")
        path = (self._records_root / run_id / "experiment_record.json").resolve()
        if self._records_root not in path.parents:
            raise ValueError("trial record escaped the experiment root")
        return path

    def _read(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        if not path.is_file():
            raise RuntimeError(f"experiment trial does not exist: {run_id}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != EXPERIMENT_TRIAL_SCHEMA_VERSION:
            raise RuntimeError("unsupported experiment trial schema")
        return value

    def _write(self, run_id: str, record: dict[str, Any]) -> None:
        with self._lock:
            path = self._path(run_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(path)


__all__ = ["EXPERIMENT_TRIAL_SCHEMA_VERSION", "ExperimentTrialRecorder"]
