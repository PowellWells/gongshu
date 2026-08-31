"""Lazy CPU adapter for the official metric Depth Anything V2 Small runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import threading
import time

import cv2
import numpy as np

from vision2grasp.contracts import RGBFrame
from vision2grasp.model_assets import (
    ModelAsset,
    ModelAssetResolver,
    ModelLocation,
)

from .contracts import DepthFrame, DepthMode, DepthSource, SpatialStage
from .interfaces import SpatialProgressCallback


MODEL_ID = "depth-anything/Depth-Anything-V2-Metric-Hypersim-Small"
MODEL_REVISION = "3bc65d4e14a6786a61acec16453c50e12bf5f338"
MODEL_FILENAME = "depth_anything_v2_metric_hypersim_vits.pth"
MODEL_LICENSE = "Apache-2.0"
MODEL_SOURCE = f"https://huggingface.co/{MODEL_ID}"
UPSTREAM_CODE_SOURCE = "https://github.com/DepthAnything/Depth-Anything-V2"
UPSTREAM_CODE_REVISION = "a561b849ebae10a6f5ef49e26c83cbbcd36c71bf"
MODEL_SIZE_BYTES = 99_222_290
MODEL_SHA256 = "b782898d8a3e8be1f639de33837ed85e9b4b73e40f8f5e5cd99067588d722545"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEPTH_PROJECT_COMPATIBLE_PATHS = (
    _PROJECT_ROOT / "artifacts" / "models" / MODEL_FILENAME,
)
MODEL_FILES: dict[str, tuple[int, str]] = {
    MODEL_FILENAME: (MODEL_SIZE_BYTES, MODEL_SHA256),
}
DEPTH_MODEL_ASSET = ModelAsset(
    key="depth-anything-v2-metric-indoor-small",
    relative_path=Path("depth-anything-v2-metric-indoor-small") / MODEL_FILENAME,
    url=f"{MODEL_SOURCE}/resolve/{MODEL_REVISION}/{MODEL_FILENAME}?download=true",
    size_bytes=MODEL_SIZE_BYTES,
    sha256=MODEL_SHA256,
    source=MODEL_SOURCE,
    revision=MODEL_REVISION,
    license=MODEL_LICENSE,
)


class DepthUnavailableError(RuntimeError):
    """Depth inference cannot proceed without inventing an output."""


@dataclass(frozen=True, slots=True)
class MonocularDepthConfig:
    device: str = "cpu"
    allow_download: bool = True
    input_size: int = 518

    def __post_init__(self) -> None:
        if self.device != "cpu":
            raise ValueError("Gongshu v0.5 monocular depth is frozen to device='cpu'")
        if self.input_size <= 0 or self.input_size % 14 != 0:
            raise ValueError("Depth Anything V2 input_size must be a positive multiple of 14")


class MonocularDepthProvider:
    """Official Hypersim Small metric-scaled inference with verified lazy loading."""

    def __init__(
        self,
        config: MonocularDepthConfig | None = None,
        *,
        asset_resolver: ModelAssetResolver | None = None,
    ) -> None:
        self._config = config or MonocularDepthConfig()
        self._asset_resolver = asset_resolver or ModelAssetResolver(
            project_compatible_paths=DEPTH_PROJECT_COMPATIBLE_PATHS
        )
        self._load_lock = threading.Lock()
        self._model = None
        self._torch = None
        self._model_location: ModelLocation | None = None

    @property
    def model_ready(self) -> bool:
        return self._model is not None

    def infer(
        self,
        frame: RGBFrame,
        progress: SpatialProgressCallback | None = None,
    ) -> DepthFrame:
        model_was_ready = self.model_ready
        load_started = time.perf_counter()
        self._ensure_loaded(progress)
        model_load_time_s = 0.0 if model_was_ready else time.perf_counter() - load_started
        assert self._model is not None
        assert self._torch is not None

        self._emit(
            progress,
            SpatialStage.DEPTH_INFERENCE,
            {
                "model_load_s": model_load_time_s,
                "model_was_ready": model_was_ready,
                "model_state": "READY",
            },
        )
        started = time.perf_counter()
        try:
            tensor, model_input_size = self._prepare_official_input(frame.rgb)
            with self._torch.inference_mode():
                prediction = self._model(tensor)
                resized = self._torch.nn.functional.interpolate(
                    prediction[:, None],
                    frame.rgb.shape[:2],
                    mode="bilinear",
                    align_corners=True,
                )[0, 0]
            values = resized.detach().cpu().numpy().astype(np.float32, copy=False)
            inference_time_s = time.perf_counter() - started
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
            model_load_time_s=model_load_time_s,
            model_was_ready=model_was_ready,
            model_input_size=model_input_size,
            model_location=(
                None if self._model_location is None else self._model_location.value
            ),
            resize_policy="OFFICIAL_LOWER_BOUND_MULTIPLE_OF_14_THEN_BILINEAR_TO_SNAPSHOT",
        )

    def _ensure_loaded(self, progress: SpatialProgressCallback | None = None) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                self._emit(
                    progress,
                    SpatialStage.MODEL_RESOLVING,
                    {"cold_start": True, "model_state": "NOT_LOADED"},
                )

                def report_model_progress(
                    stage: str,
                    details: Mapping[str, object],
                ) -> None:
                    self._emit(progress, SpatialStage(stage), dict(details))

                resolved = self._asset_resolver.resolve(
                    DEPTH_MODEL_ASSET,
                    allow_download=self._config.allow_download,
                    progress=report_model_progress,
                )
                self._emit(
                    progress,
                    SpatialStage.MODEL_LOADING,
                    {
                        "model_location": resolved.location.value,
                        "resolver_diagnostics": [
                            dict(item) for item in resolved.diagnostics
                        ],
                        "cold_start": True,
                    },
                )
                import torch

                from vision2grasp._vendor.depth_anything_v2.dpt import DepthAnythingV2

                model = DepthAnythingV2(
                    encoder="vits",
                    features=64,
                    out_channels=[48, 96, 192, 384],
                    max_depth=20.0,
                )
                state_dict = torch.load(
                    resolved.path,
                    map_location="cpu",
                    weights_only=True,
                )
                model.load_state_dict(state_dict)
                model.to("cpu")
                model.eval()
            except Exception as error:
                wrapped = DepthUnavailableError(
                    f"depth backend could not be loaded: {error}"
                )
                wrapped.code = getattr(error, "code", "MODEL_LOAD_FAILED")
                raise wrapped from error
            self._model = model
            self._torch = torch
            self._model_location = resolved.location

    def _prepare_official_input(
        self,
        image_rgb: np.ndarray,
    ) -> tuple[object, tuple[int, int]]:
        assert self._torch is not None
        from torchvision.transforms import Compose

        from vision2grasp._vendor.depth_anything_v2.util.transform import (
            NormalizeImage,
            PrepareForNet,
            Resize,
        )

        transform = Compose(
            [
                Resize(
                    width=self._config.input_size,
                    height=self._config.input_size,
                    resize_target=False,
                    keep_aspect_ratio=True,
                    ensure_multiple_of=14,
                    resize_method="lower_bound",
                    image_interpolation_method=cv2.INTER_CUBIC,
                ),
                NormalizeImage(
                    mean=[0.485, 0.456, 0.406],
                    std=[0.229, 0.224, 0.225],
                ),
                PrepareForNet(),
            ]
        )
        normalized = np.asarray(image_rgb, dtype=np.float32) / 255.0
        transformed = transform({"image": normalized})["image"]
        model_height, model_width = transformed.shape[1:]
        tensor = self._torch.from_numpy(transformed).unsqueeze(0).to("cpu")
        return tensor, (int(model_width), int(model_height))

    @staticmethod
    def _emit(
        progress: SpatialProgressCallback | None,
        stage: SpatialStage,
        details: dict[str, object] | None = None,
    ) -> None:
        if progress is not None:
            progress(stage, details)
