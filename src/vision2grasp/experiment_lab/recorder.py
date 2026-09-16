"""Experiment Lab trial records for Gongshu local-image runs."""

from __future__ import annotations

import json
import hashlib
import io
from pathlib import Path
import threading
from typing import Any, TYPE_CHECKING

import cv2
import numpy as np

from vision2grasp.intelligence import AlgorithmDecision
from vision2grasp.sources.local_image import LocalImageObservation

if TYPE_CHECKING:
    from vision2grasp.spatial_perception import SpatialObservation
    from vision2grasp.target_perception import TargetSceneSnapshot


EXPERIMENT_TRIAL_SCHEMA_VERSION = "gongshu.experiment-trial/v2"


class ExperimentTrialRecorder:
    """Persist experiment evidence without owning scenes, algorithms, or runtime."""

    def __init__(self, records_root: Path) -> None:
        self._records_root = Path(records_root).resolve()
        self._lock = threading.RLock()

    def start(
        self,
        observation: LocalImageObservation,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "schema_version": EXPERIMENT_TRIAL_SCHEMA_VERSION,
            "trial_id": observation.run_id,
            "status": "OBSERVATION_READY",
            "input": observation.as_dict(),
            "experiment_parameters": dict(parameters or {}),
            "algorithm": None,
            "decision": None,
            "condition_report": None,
            "perception": None,
            "object_reconstruction": None,
            "mujoco_model": None,
            "artifacts": {},
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
            request = dict(result.get("validation_request") or {})
            telemetry = dict(result.get("telemetry") or {})
            if request.get("object_reconstruction") is not None:
                record["object_reconstruction"] = request["object_reconstruction"]
            xml_sha256 = telemetry.get("mujoco_model_xml_sha256")
            if xml_sha256:
                record["mujoco_model"] = {
                    "xml_sha256": xml_sha256,
                    "proxy_geometry": telemetry.get("object_reconstruction", {}).get(
                        "proxy_geometry"
                    ),
                }
            record["status"] = "COMPLETED"
            self._write(run_id, record)

    def record_perception(
        self,
        run_id: str,
        snapshot: "TargetSceneSnapshot",
        observation: "SpatialObservation",
    ) -> None:
        """Persist the exact selected mask, depth, and cloud used downstream."""

        if snapshot.snapshot_id != observation.snapshot_id:
            raise ValueError("experiment evidence snapshot does not match observation")
        with self._lock:
            record = self._read(run_id)
            artifacts = dict(record.get("artifacts") or {})
            rgb_bgr = cv2.cvtColor(snapshot.frame.rgb, cv2.COLOR_RGB2BGR)
            ok, rgb = cv2.imencode(".jpg", rgb_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise RuntimeError("failed to encode pipeline RGB evidence")
            ok, mask = cv2.imencode(
                ".png", np.asarray(snapshot.target.mask, dtype=np.uint8) * 255
            )
            if not ok:
                raise RuntimeError("failed to encode target mask evidence")
            artifacts["pipeline_rgb"] = self._write_artifact(
                run_id, "pipeline_rgb.jpg", rgb.tobytes()
            )
            artifacts["target_mask"] = self._write_artifact(
                run_id, "target_mask.png", mask.tobytes()
            )
            artifacts["depth"] = self._write_numpy(
                run_id, "depth.npy", observation.depth_frame.values
            )
            artifacts["point_cloud"] = self._write_numpy(
                run_id, "point_cloud.npy", observation.target_point_cloud
            )
            record["condition_report"] = (
                None
                if snapshot.condition_report is None
                else snapshot.condition_report.public_metadata()
            )
            record["perception"] = {
                "scene_snapshot": snapshot.public_metadata(),
                "spatial_observation": observation.public_metadata(),
            }
            record["artifacts"] = artifacts
            record["status"] = "PERCEPTION_RECORDED"
            self._write(run_id, record)

    def record_validation_request(
        self, run_id: str, validation_state: dict[str, Any]
    ) -> None:
        with self._lock:
            record = self._read(run_id)
            request = dict(validation_state.get("request") or {})
            record["object_reconstruction"] = request.get("object_reconstruction")
            record["mujoco_model"] = dict(validation_state.get("telemetry") or {}).get(
                "mujoco_model_xml_sha256"
            )
            record["status"] = "VALIDATION_REQUEST_RECORDED"
            self._write(run_id, record)

    def _path(self, run_id: str) -> Path:
        if not run_id.startswith("offline-") or any(part in run_id for part in ("/", "\\", "..")):
            raise ValueError("invalid offline trial identifier")
        path = (self._records_root / run_id / "experiment_record.json").resolve()
        if self._records_root not in path.parents:
            raise ValueError("trial record escaped the experiment root")
        return path

    def _write_artifact(self, run_id: str, name: str, payload: bytes) -> dict[str, Any]:
        root = self._path(run_id).parent.resolve()
        path = (root / name).resolve()
        if root not in path.parents or path.parent != root:
            raise ValueError("experiment artifact escaped the trial directory")
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(path)
        return {
            "path": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }

    def _write_numpy(self, run_id: str, name: str, values: np.ndarray) -> dict[str, Any]:
        buffer = io.BytesIO()
        np.save(buffer, np.asarray(values), allow_pickle=False)
        return self._write_artifact(run_id, name, buffer.getvalue())

    def _read(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        if not path.is_file():
            raise RuntimeError(f"experiment trial does not exist: {run_id}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") not in {
            "gongshu.experiment-trial/v1",
            EXPERIMENT_TRIAL_SCHEMA_VERSION,
        }:
            raise RuntimeError("unsupported experiment trial schema")
        if value.get("schema_version") != EXPERIMENT_TRIAL_SCHEMA_VERSION:
            value["schema_version"] = EXPERIMENT_TRIAL_SCHEMA_VERSION
            value.setdefault("condition_report", None)
            value.setdefault("perception", None)
            value.setdefault("object_reconstruction", None)
            value.setdefault("mujoco_model", None)
            value.setdefault("artifacts", {})
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
