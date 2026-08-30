"""Lazy CPU adapter for the official metric Depth Anything V2 Small model."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen

import numpy as np

from vision2grasp.contracts import RGBFrame

from .contracts import DepthFrame, DepthMode, DepthSource


MODEL_ID = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
MODEL_REVISION = "8078d68a9c75a972131914f6afd0c1723be0da7f"
MODEL_LICENSE = "Apache-2.0"
MODEL_SOURCE = f"https://huggingface.co/{MODEL_ID}"
MODEL_FILES: dict[str, tuple[int, str]] = {
    "config.json": (
        1063,
        "0b1d9fc591693d16b864249a9cfcf5264c8c00be999c1643fa1c64dc105d55f8",
    ),
    "preprocessor_config.json": (
        437,
        "533b16a60445d7cab5086d39b45f92be45624b977972c62d5984d93e98366063",
    ),
    "model.safetensors": (
        99_173_660,
        "e990eb82fbf11b05b7813261196a2b841bdcf5a05f64396724a8987fa90504a3",
    ),
}


class DepthUnavailableError(RuntimeError):
    """Depth inference cannot proceed without inventing an output."""


@dataclass(frozen=True, slots=True)
class MonocularDepthConfig:
    model_directory: Path = (
        Path(__file__).resolve().parents[3]
        / "artifacts"
        / "models"
        / "depth-anything-v2-metric-indoor-small-hf"
    )
    device: str = "cpu"
    allow_download: bool = True

    def __post_init__(self) -> None:
        if self.device != "cpu":
            raise ValueError("Gongshu v0.5 monocular depth is frozen to device='cpu'")


class MonocularDepthProvider:
    """Metric-scaled indoor monocular depth with delayed verified loading."""

    def __init__(self, config: MonocularDepthConfig | None = None) -> None:
        self._config = config or MonocularDepthConfig()
        self._load_lock = threading.Lock()
        self._processor = None
        self._model = None
        self._torch = None

    def infer(self, frame: RGBFrame) -> DepthFrame:
        self._ensure_loaded()
        assert self._processor is not None
        assert self._model is not None
        assert self._torch is not None
        torch = self._torch
        try:
            inputs = self._processor(images=frame.rgb, return_tensors="pt")
            started = time.perf_counter()
            with torch.inference_mode():
                output = self._model(**inputs)
                processed = self._processor.post_process_depth_estimation(
                    output,
                    target_sizes=[frame.rgb.shape[:2]],
                )
            inference_time_s = time.perf_counter() - started
            if len(processed) != 1 or "predicted_depth" not in processed[0]:
                raise RuntimeError("depth post-processing returned an invalid result")
            values = (
                processed[0]["predicted_depth"]
                .detach()
                .cpu()
                .numpy()
                .astype(np.float32, copy=False)
            )
        except Exception as error:
            raise DepthUnavailableError(f"depth inference failed: {error}") from error
        if values.shape != frame.rgb.shape[:2]:
            raise DepthUnavailableError("depth output does not match frozen RGB frame")
        if not np.any(np.isfinite(values) & (values > 0.0)):
            raise DepthUnavailableError("depth backend returned no valid positive depth")
        return DepthFrame(
            source_frame_id=frame.frame_id,
            source_timestamp_s=frame.timestamp_s,
            values=values,
            source=DepthSource.MONOCULAR,
            native_mode=DepthMode.METRIC,
            inference_time_s=inference_time_s,
        )

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            self._ensure_model_files()
            try:
                import torch
                from transformers import AutoImageProcessor, AutoModelForDepthEstimation

                model_dir = str(self._config.model_directory)
                processor = AutoImageProcessor.from_pretrained(
                    model_dir,
                    local_files_only=True,
                    use_fast=False,
                )
                model = AutoModelForDepthEstimation.from_pretrained(
                    model_dir,
                    local_files_only=True,
                )
                model.to("cpu")
                model.eval()
            except Exception as error:
                raise DepthUnavailableError(f"depth backend could not be loaded: {error}") from error
            self._processor = processor
            self._model = model
            self._torch = torch

    def _ensure_model_files(self) -> None:
        directory = self._config.model_directory
        directory.mkdir(parents=True, exist_ok=True)
        for filename, (expected_size, expected_sha256) in MODEL_FILES.items():
            destination = directory / filename
            if self._verified(destination, expected_size, expected_sha256):
                continue
            if not self._config.allow_download:
                raise DepthUnavailableError(
                    f"verified depth model file is unavailable: {filename}"
                )
            self._download_verified(
                filename,
                destination,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
            )

    @staticmethod
    def _verified(path: Path, expected_size: int, expected_sha256: str) -> bool:
        if not path.is_file() or path.stat().st_size != expected_size:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha256

    def _download_verified(
        self,
        filename: str,
        destination: Path,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        url = f"{MODEL_SOURCE}/resolve/{MODEL_REVISION}/{filename}"
        temporary = destination.with_suffix(destination.suffix + ".download")
        digest = hashlib.sha256()
        size = 0
        try:
            request = Request(url, headers={"User-Agent": "Gongshu-v0.5/1.0"})
            with urlopen(request, timeout=60) as response, temporary.open("wb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    stream.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if size != expected_size or digest.hexdigest() != expected_sha256:
                raise DepthUnavailableError(
                    f"downloaded depth model file failed integrity validation: {filename}"
                )
            temporary.replace(destination)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            if isinstance(error, DepthUnavailableError):
                raise
            raise DepthUnavailableError(
                f"depth model download failed for {filename}: {error}"
            ) from error
