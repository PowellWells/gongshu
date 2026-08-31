"""Session-first MuJoCo recording, playback, and explicit persistence contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from .validation_contracts import CameraMode, SimulationState, ValidationResult


RECORDING_SCHEMA_VERSION: Final = "gongshu.simulation-recording/v1"
SAVED_RUN_SCHEMA_VERSION: Final = "gongshu.saved-validation-run/v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")


def gongshu_user_data_root() -> Path:
    """Return a runtime-data root that is deliberately outside the Git checkout."""

    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "XUANSHU-LAB" / "Gongshu"


def default_recordings_root() -> Path:
    return gongshu_user_data_root() / "recordings"


def default_exports_root() -> Path:
    return gongshu_user_data_root() / "exports"


@dataclass(frozen=True, slots=True)
class ContactState:
    position_world: tuple[float, float, float]
    normal_world: tuple[float, float, float]
    geom1: str
    geom2: str
    distance_m: float

    def public_metadata(self) -> dict[str, Any]:
        return {
            "position_world": list(self.position_world),
            "normal_world": list(self.normal_world),
            "geom1": self.geom1,
            "geom2": self.geom2,
            "distance_m": self.distance_m,
        }


@dataclass(frozen=True, slots=True)
class RecordingEvent:
    timestamp_s: float
    name: str
    state: str

    def public_metadata(self) -> dict[str, Any]:
        return {"timestamp_s": self.timestamp_s, "name": self.name, "state": self.state}


@dataclass(frozen=True, slots=True)
class ValidationRun:
    run_id: str
    result: ValidationResult
    source_frame_id: int | None
    target_instance_id: str | None
    grasp_plan_id: str | None
    recording_id: str

    def public_metadata(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "result": self.result.public_metadata(),
            "source_frame_id": self.source_frame_id,
            "target_instance_id": self.target_instance_id,
            "grasp_plan_id": self.grasp_plan_id,
            "recording_id": self.recording_id,
        }


@dataclass(slots=True)
class PlaybackSession:
    current_time: float = 0.0
    playback_speed: float = 1.0
    paused: bool = True
    camera_mode: CameraMode = CameraMode.AUTO_CINEMATIC
    overlay_mode: str = "OFF"

    def public_metadata(self, *, duration_s: float) -> dict[str, Any]:
        return {
            "current_time": float(np.clip(self.current_time, 0.0, duration_s)),
            "duration_s": duration_s,
            "playback_speed": self.playback_speed,
            "paused": self.paused,
            "camera_mode": self.camera_mode.value,
            "overlay_mode": self.overlay_mode,
        }


@dataclass(frozen=True, slots=True)
class SimulationRecording:
    recording_id: str
    run_id: str
    created_at: str
    sample_hz: float
    timestamps: NDArray[np.float64]
    qpos: NDArray[np.float64]
    qvel: NDArray[np.float64]
    gripper_states: NDArray[np.float64]
    target_poses: NDArray[np.float64]
    target_velocities: NDArray[np.float64]
    eef_positions: NDArray[np.float64]
    collision_states: NDArray[np.bool_]
    lift_heights: NDArray[np.float64]
    validation_states: tuple[str, ...]
    contacts: tuple[tuple[ContactState, ...], ...]
    events: tuple[RecordingEvent, ...]
    result: ValidationResult
    request_metadata: dict[str, Any]
    compatibility: dict[str, Any]
    model_xml: str = field(repr=False)
    saved_path: str | None = None

    def __post_init__(self) -> None:
        count = len(self.timestamps)
        if not _SAFE_ID.fullmatch(self.recording_id) or not _SAFE_ID.fullmatch(self.run_id):
            raise ValueError("recording and run identifiers must be path-safe")
        if count < 1:
            raise ValueError("SimulationRecording requires at least one sample")
        for name in (
            "qpos", "qvel", "gripper_states", "target_poses", "target_velocities",
            "eef_positions", "collision_states", "lift_heights",
        ):
            if len(getattr(self, name)) != count:
                raise ValueError(f"{name} sample count does not match timestamps")
        if len(self.validation_states) != count or len(self.contacts) != count:
            raise ValueError("state/contact sample count does not match timestamps")
        if not np.all(np.isfinite(self.timestamps)) or np.any(np.diff(self.timestamps) < 0.0):
            raise ValueError("recording timestamps must be finite and monotonic")
        for name in (
            "timestamps", "qpos", "qvel", "gripper_states", "target_poses",
            "target_velocities", "eef_positions", "collision_states", "lift_heights",
        ):
            value = np.ascontiguousarray(np.asarray(getattr(self, name)).copy())
            value.setflags(write=False)
            object.__setattr__(self, name, value)

    @property
    def duration_s(self) -> float:
        return float(self.timestamps[-1])

    @property
    def saved(self) -> bool:
        return self.saved_path is not None

    def index_at(self, timestamp_s: float) -> int:
        value = float(np.clip(timestamp_s, 0.0, self.duration_s))
        right = int(np.searchsorted(self.timestamps, value, side="left"))
        if right <= 0:
            return 0
        if right >= len(self.timestamps):
            return len(self.timestamps) - 1
        left = right - 1
        return left if value - self.timestamps[left] <= self.timestamps[right] - value else right

    def public_summary(self) -> dict[str, Any]:
        return {
            "schema_version": RECORDING_SCHEMA_VERSION,
            "recording_id": self.recording_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "duration_s": self.duration_s,
            "sample_hz": self.sample_hz,
            "sample_count": len(self.timestamps),
            "result": self.result.public_metadata(),
            "source_frame_id": self.request_metadata.get("grasp_plan", {}).get("source_frame_id"),
            "target_instance_id": self.request_metadata.get("grasp_plan", {}).get("target_id"),
            "grasp_plan_id": self.request_metadata.get("grasp_plan", {}).get("plan_id"),
            "storage": "SAVED" if self.saved else "SESSION_ONLY",
            "saved_path": self.saved_path,
            "compatibility": dict(self.compatibility),
        }

    def manifest(self) -> dict[str, Any]:
        return {
            **self.public_summary(),
            "schema_version": SAVED_RUN_SCHEMA_VERSION,
            "storage": "SAVED",
            "saved_path": None,
            "request": self.request_metadata,
            "events": [event.public_metadata() for event in self.events],
            "contacts": [
                [contact.public_metadata() for contact in sample]
                for sample in self.contacts
            ],
            "files": {"states": "states.npz", "model": "model.xml"},
        }


@dataclass(frozen=True, slots=True)
class PlanningVisualizationRecording:
    recording_id: str
    run_id: str
    created_at: str
    rejection_reason: str
    metadata: dict[str, Any]
    preview_jpeg: bytes = field(repr=False)
    saved_path: str | None = None

    @property
    def saved(self) -> bool:
        return self.saved_path is not None

    def public_summary(self) -> dict[str, Any]:
        return {
            "schema_version": "gongshu.planning-visualization-recording/v1",
            "kind": "PLANNING_REJECTED_VISUALIZATION",
            "recording_id": self.recording_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "duration_s": 0.0,
            "result": {"state": "PLANNING_REJECTED", "reason": self.rejection_reason},
            "rejection_reason": self.rejection_reason,
            "storage": "SAVED" if self.saved else "SESSION_ONLY",
            "saved_path": self.saved_path,
        }


def save_planning_visualization(
    recording: PlanningVisualizationRecording, root: Path | None = None
) -> PlanningVisualizationRecording:
    destination_root = Path(root or default_recordings_root()).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / recording.recording_id
    if destination.exists():
        raise FileExistsError(f"recording already saved: {recording.recording_id}")
    destination.mkdir()
    try:
        manifest = {
            **recording.public_summary(),
            "storage": "SAVED",
            "saved_path": None,
            "metadata": recording.metadata,
            "files": {"preview": "preview.jpg"},
        }
        (destination / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (destination / "preview.jpg").write_bytes(recording.preview_jpeg)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    object.__setattr__(recording, "saved_path", str(destination))
    return recording

def save_recording(recording: SimulationRecording, root: Path | None = None) -> SimulationRecording:
    """Persist only after an explicit user action, using an atomic directory move."""

    destination_root = Path(root or default_recordings_root()).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / recording.recording_id
    if destination.exists():
        raise FileExistsError(f"recording already saved: {recording.recording_id}")
    temporary = destination_root / f".{recording.recording_id}.saving"
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir()
    try:
        (temporary / "manifest.json").write_text(
            json.dumps(recording.manifest(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (temporary / "model.xml").write_text(recording.model_xml, encoding="utf-8")
        np.savez_compressed(
            temporary / "states.npz",
            timestamps=recording.timestamps,
            qpos=recording.qpos,
            qvel=recording.qvel,
            gripper_states=recording.gripper_states,
            target_poses=recording.target_poses,
            target_velocities=recording.target_velocities,
            eef_positions=recording.eef_positions,
            collision_states=recording.collision_states,
            lift_heights=recording.lift_heights,
            validation_states=np.asarray(recording.validation_states, dtype="U32"),
        )
        temporary.replace(destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    object.__setattr__(recording, "saved_path", str(destination))
    return recording


def list_saved_runs(root: Path | None = None) -> list[dict[str, Any]]:
    location = Path(root or default_recordings_root())
    if not location.exists():
        return []
    runs: list[dict[str, Any]] = []
    for manifest_path in location.glob("*/manifest.json"):
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
            schema = document.get("schema_version")
            if schema not in {
                SAVED_RUN_SCHEMA_VERSION,
                "gongshu.planning-visualization-recording/v1",
            }:
                continue
            summary = {
                "schema_version": document["schema_version"],
                "recording_id": document["recording_id"],
                "run_id": document["run_id"],
                "created_at": document["created_at"],
                "duration_s": document["duration_s"],
                "result": document["result"],
                "storage": "SAVED",
                "saved_path": str(manifest_path.parent),
                "compatibility": document.get("compatibility", {}),
            }
            if schema == SAVED_RUN_SCHEMA_VERSION:
                summary.update(
                    sample_hz=document["sample_hz"], sample_count=document["sample_count"]
                )
            else:
                summary.update(kind="PLANNING_REJECTED_VISUALIZATION")
            runs.append(summary)
        except (OSError, ValueError, TypeError):
            continue
    return sorted(runs, key=lambda item: str(item.get("created_at", "")), reverse=True)


def load_recording(recording_id: str, root: Path | None = None) -> SimulationRecording:
    if not _SAFE_ID.fullmatch(recording_id):
        raise ValueError("invalid recording identifier")
    location = Path(root or default_recordings_root()) / recording_id
    manifest = json.loads((location / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SAVED_RUN_SCHEMA_VERSION:
        raise ValueError("unsupported saved recording schema")
    model_xml = (location / "model.xml").read_text(encoding="utf-8")
    expected_hash = str(manifest.get("compatibility", {}).get("model_sha256", ""))
    import hashlib

    actual_hash = hashlib.sha256(model_xml.encode("utf-8")).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError("saved MuJoCo model fingerprint mismatch")
    with np.load(location / "states.npz", allow_pickle=False) as states:
        result_data = manifest["result"]
        result = ValidationResult(
            state=SimulationState(str(result_data["state"])),
            reason=result_data.get("reason"),
            state_machine_complete=bool(result_data["state_machine_complete"]),
            invalid_table_collision=bool(result_data["invalid_table_collision"]),
            gripper_close_executed=bool(result_data["gripper_close_executed"]),
            lift_height_m=float(result_data["lift_height_m"]),
            stable_window_passed=bool(result_data["stable_window_passed"]),
        )
        contacts = tuple(
            tuple(
                ContactState(
                    tuple(float(value) for value in contact["position_world"]),
                    tuple(float(value) for value in contact["normal_world"]),
                    str(contact["geom1"]), str(contact["geom2"]), float(contact["distance_m"]),
                )
                for contact in sample
            )
            for sample in manifest["contacts"]
        )
        events = tuple(
            RecordingEvent(float(event["timestamp_s"]), str(event["name"]), str(event["state"]))
            for event in manifest["events"]
        )
        return SimulationRecording(
            recording_id=str(manifest["recording_id"]),
            run_id=str(manifest["run_id"]),
            created_at=str(manifest["created_at"]),
            sample_hz=float(manifest["sample_hz"]),
            timestamps=states["timestamps"], qpos=states["qpos"], qvel=states["qvel"],
            gripper_states=states["gripper_states"], target_poses=states["target_poses"],
            target_velocities=states["target_velocities"], eef_positions=states["eef_positions"],
            collision_states=states["collision_states"], lift_heights=states["lift_heights"],
            validation_states=tuple(str(value) for value in states["validation_states"].tolist()),
            contacts=contacts, events=events, result=result,
            request_metadata=dict(manifest["request"]),
            compatibility=dict(manifest["compatibility"]), model_xml=model_xml,
            saved_path=str(location),
        )


def load_planning_visualization(
    recording_id: str, root: Path | None = None
) -> PlanningVisualizationRecording:
    if not _SAFE_ID.fullmatch(recording_id):
        raise ValueError("invalid recording identifier")
    location = Path(root or default_recordings_root()) / recording_id
    manifest = json.loads((location / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "gongshu.planning-visualization-recording/v1":
        raise ValueError("unsupported planning visualization schema")
    return PlanningVisualizationRecording(
        recording_id=str(manifest["recording_id"]), run_id=str(manifest["run_id"]),
        created_at=str(manifest["created_at"]),
        rejection_reason=str(manifest["rejection_reason"]),
        metadata=dict(manifest["metadata"]),
        preview_jpeg=(location / "preview.jpg").read_bytes(), saved_path=str(location),
    )


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
