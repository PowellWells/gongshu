"""Single-image input adapter for Gongshu's existing observation pipeline."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import threading
from typing import Final
from uuid import uuid4

import cv2
import numpy as np

from vision2grasp.contracts import RGBFrame


LOCAL_IMAGE_SCHEMA_VERSION: Final = "gongshu.local-image-observation/v0.1"
OFFLINE_RUN_SCHEMA_VERSION: Final = "gongshu.offline-run/v0.1"
MAX_LOCAL_IMAGE_BYTES: Final = 15 * 1024 * 1024
_ALLOWED_SUFFIXES: Final = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass(frozen=True, slots=True)
class LocalImageObservation:
    """Metadata for one archived image exposed through the shared RGB contract."""

    source: str
    image_path: str
    image_name: str
    timestamp: str
    status: str
    run_id: str
    sha256: str
    width: int
    height: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": LOCAL_IMAGE_SCHEMA_VERSION,
            "source": self.source,
            "image_path": self.image_path,
            "image_name": self.image_name,
            "timestamp": self.timestamp,
            "status": self.status,
            "run_id": self.run_id,
            "sha256": self.sha256,
            "resolution": {"width": self.width, "height": self.height},
        }


class LocalImageAdapter:
    """Validate, archive, and expose exactly one local image at a time."""

    def __init__(self, records_root: Path) -> None:
        self._records_root = Path(records_root)
        self._lock = threading.RLock()
        self._source_rgb: np.ndarray | None = None
        self._preview_jpeg: bytes | None = None
        self._observation: LocalImageObservation | None = None
        self._record_path: Path | None = None
        self._record: dict[str, object] | None = None
        self._next_frame_id = 0

    def load(self, filename: str, payload: bytes) -> LocalImageObservation:
        image_name = Path(str(filename).strip()).name
        suffix = Path(image_name).suffix.lower()
        if not image_name or suffix not in _ALLOWED_SUFFIXES:
            raise ValueError("local image must be JPG, JPEG, PNG, WEBP, or BMP")
        if not payload:
            raise ValueError("local image is empty")
        if len(payload) > MAX_LOCAL_IMAGE_BYTES:
            raise ValueError("local image exceeds the 15 MB limit")

        bgr = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None or bgr.ndim != 3 or bgr.shape[2] != 3:
            raise ValueError("unable to decode local image")
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        ok, encoded = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise ValueError("unable to prepare local image preview")

        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        run_id = f"offline-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{uuid4().hex[:8]}"
        run_directory = self._records_root / run_id
        run_directory.mkdir(parents=True, exist_ok=False)
        archived_path = run_directory / f"input{suffix}"
        archived_path.write_bytes(payload)
        relative_path = archived_path.relative_to(self._records_root.parent.parent).as_posix()
        observation = LocalImageObservation(
            source="local_image",
            image_path=relative_path,
            image_name=image_name,
            timestamp=timestamp,
            status="ready",
            run_id=run_id,
            sha256=hashlib.sha256(payload).hexdigest(),
            width=int(rgb.shape[1]),
            height=int(rgb.shape[0]),
        )
        record = {
            "schema_version": OFFLINE_RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "image_name": image_name,
            "image_path": relative_path,
            "image_sha256": observation.sha256,
            "timestamp": timestamp,
            "input_source": "local_image",
            "pipeline_status": "OBSERVATION_READY",
            "mujoco_result": None,
        }
        record_path = run_directory / "run.json"
        self._write_record(record_path, record)
        with self._lock:
            self._source_rgb = rgb
            self._preview_jpeg = encoded.tobytes()
            self._observation = observation
            self._record_path = record_path
            self._record = record
            self._next_frame_id = 0
        return observation

    def capture(self) -> RGBFrame:
        with self._lock:
            if self._source_rgb is None:
                raise RuntimeError("no local image has been loaded")
            frame = RGBFrame(
                frame_id=self._next_frame_id,
                timestamp_s=datetime.now().timestamp(),
                camera_name="local-image",
                rgb=self._source_rgb.copy(),
            )
            self._next_frame_id += 1
            return frame

    def preview_jpeg(self) -> bytes | None:
        with self._lock:
            return None if self._preview_jpeg is None else bytes(self._preview_jpeg)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "schema_version": LOCAL_IMAGE_SCHEMA_VERSION,
                "status": "ready" if self._observation is not None else "waiting",
                "observation": (
                    None if self._observation is None else self._observation.as_dict()
                ),
                "offline_run": None if self._record is None else dict(self._record),
            }

    def active_run_id(self) -> str | None:
        with self._lock:
            return None if self._observation is None else self._observation.run_id

    def record_pipeline_status(self, status: str, *, run_id: str | None = None) -> None:
        self._update_record("pipeline_status", str(status), run_id=run_id)

    def record_mujoco_result(
        self, result: dict[str, object], *, run_id: str | None = None
    ) -> None:
        self._update_record("mujoco_result", dict(result), run_id=run_id)

    def _update_record(self, key: str, value: object, *, run_id: str | None) -> None:
        with self._lock:
            if self._record is None or self._record_path is None or self._observation is None:
                return
            if run_id is not None and run_id != self._observation.run_id:
                return
            self._record[key] = value
            self._write_record(self._record_path, self._record)

    @staticmethod
    def _write_record(path: Path, record: dict[str, object]) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)


__all__ = [
    "LOCAL_IMAGE_SCHEMA_VERSION",
    "MAX_LOCAL_IMAGE_BYTES",
    "OFFLINE_RUN_SCHEMA_VERSION",
    "LocalImageAdapter",
    "LocalImageObservation",
]
