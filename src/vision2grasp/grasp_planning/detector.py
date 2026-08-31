"""Verified target-aware pixel-wise antipodal grasp inference."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sys
import threading
import time
from types import ModuleType

import cv2
import numpy as np
import torch

from vision2grasp._vendor.grconvnet import GenerativeResnet, GraspModel, ResidualBlock
from vision2grasp.model_assets import ModelAsset, ModelAssetResolver
from vision2grasp.spatial_perception import SpatialObservation
from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import GraspMaps, GraspStage


UPSTREAM_CODE_REVISION = "183c6f68c44c1c7ff0f07707e2db6fcfd6840d2d"
MODEL_REVISION = "jacquard-rgbd-grconvnet3-drop0-ch32/epoch_48_iou_0.93"
GRCONVNET_MODEL_ASSET = ModelAsset(
    key="grconvnet-jacquard-rgbd",
    relative_path=Path("grconvnet") / "jacquard-rgbd-grconvnet3-epoch48-iou0.93.pt",
    url=(
        "https://raw.githubusercontent.com/skumra/robotic-grasping/"
        f"{UPSTREAM_CODE_REVISION}/trained-models/"
        "jacquard-rgbd-grconvnet3-drop0-ch32/epoch_48_iou_0.93"
    ),
    size_bytes=7_661_004,
    sha256="adfb2cbbb8df2708a732e12ddc4db114f3ec399ffb5d403ca75c5b5b9e769171",
    source="https://github.com/skumra/robotic-grasping",
    revision=MODEL_REVISION,
    license="BSD-3-Clause",
)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
GRCONVNET_PROJECT_COMPATIBLE_PATHS = (
    _PROJECT_ROOT / "artifacts" / "models" / GRCONVNET_MODEL_ASSET.relative_path.name,
)


GraspProgressCallback = Callable[[GraspStage, Mapping[str, object] | None], None]


@dataclass(frozen=True, slots=True)
class GRConvNetDetectorConfig:
    device: str = "auto"
    input_size: int = 224
    crop_margin: float = 1.35

    def __post_init__(self) -> None:
        if self.device.lower() not in {"auto", "cpu", "cuda"}:
            raise ValueError("grasp detector device must be auto, cpu, or cuda")
        if self.input_size != 224:
            raise ValueError("the pinned GR-ConvNet checkpoint requires 224x224 input")
        if not 1.0 <= self.crop_margin <= 2.0:
            raise ValueError("crop_margin must be in [1, 2]")


class GRConvNetDetector:
    """Lazy singleton detector that retains one verified model instance."""

    def __init__(
        self,
        config: GRConvNetDetectorConfig | None = None,
        resolver: ModelAssetResolver | None = None,
    ) -> None:
        self.config = config or GRConvNetDetectorConfig()
        self._resolver = resolver or ModelAssetResolver(
            project_compatible_paths=GRCONVNET_PROJECT_COMPATIBLE_PATHS
        )
        self._model: GenerativeResnet | None = None
        self._device: torch.device | None = None
        self._model_location: str | None = None
        self._lock = threading.Lock()

    @property
    def model_ready(self) -> bool:
        return self._model is not None

    @property
    def compute_device(self) -> str:
        return "PENDING" if self._device is None else str(self._device).upper()

    def infer(
        self,
        snapshot: TargetSceneSnapshot,
        observation: SpatialObservation,
        progress: GraspProgressCallback | None = None,
    ) -> GraspMaps:
        self._validate_inputs(snapshot, observation)
        with self._lock:
            model_was_ready = self._model is not None
            load_time = 0.0
            if self._model is None:
                started = time.perf_counter()
                self._load(progress)
                load_time = time.perf_counter() - started
            assert self._model is not None and self._device is not None
            tensor, crop = self._prepare_input(snapshot, observation)
            self._emit(
                progress,
                GraspStage.GRASP_INFERENCE,
                {
                    "compute_device": str(self._device).upper(),
                    "model_was_ready": model_was_ready,
                    "model_load_s": load_time,
                },
            )
            tensor = tensor.to(self._device, non_blocking=self._device.type == "cuda")
            if self._device.type == "cuda":
                torch.cuda.synchronize(self._device)
            started = time.perf_counter()
            with torch.inference_mode():
                position, cosine, sine, width = self._model(tensor)
            if self._device.type == "cuda":
                torch.cuda.synchronize(self._device)
            inference_time = time.perf_counter() - started
            quality = position.detach().float().cpu().numpy().squeeze()
            angle = (
                torch.atan2(sine, cosine).mul(0.5).detach().float().cpu().numpy().squeeze()
            )
            width_px = width.detach().float().cpu().numpy().squeeze() * 150.0
            quality = cv2.GaussianBlur(quality, (0, 0), 2.0)
            angle = cv2.GaussianBlur(angle, (0, 0), 2.0)
            width_px = cv2.GaussianBlur(width_px, (0, 0), 1.0)
            return self._restore_maps(
                snapshot,
                crop,
                quality,
                angle,
                width_px,
                inference_time=inference_time,
                model_load_time=load_time,
                model_was_ready=model_was_ready,
            )

    def _load(self, progress: GraspProgressCallback | None) -> None:
        def resolver_progress(stage: str, details: Mapping[str, object]) -> None:
            try:
                mapped = GraspStage(stage)
            except ValueError:
                mapped = GraspStage.MODEL_RESOLVING
            self._emit(progress, mapped, details)

        resolved = self._resolver.resolve(
            GRCONVNET_MODEL_ASSET,
            progress=resolver_progress,
        )
        self._emit(
            progress,
            GraspStage.MODEL_LOADING,
            {
                "model_location": resolved.location.value,
                "compute_device": self._resolve_device().upper(),
            },
        )
        # The upstream checkpoint is a full torch.save(model) pickle. It is
        # loaded only after exact size and SHA-256 verification, then copied
        # into this vendored architecture via state_dict.
        with self._legacy_module_aliases():
            legacy = torch.load(resolved.path, map_location="cpu", weights_only=False)
        model = GenerativeResnet(input_channels=4, channel_size=32, dropout=False)
        model.load_state_dict(legacy.state_dict(), strict=True)
        del legacy
        device = torch.device(self._resolve_device())
        model.eval().to(device)
        self._model = model
        self._device = device
        self._model_location = resolved.location.value

    def _resolve_device(self) -> str:
        requested = self.config.device.lower()
        if requested == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        if requested == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested for grasp inference but is unavailable")
        return requested

    def _prepare_input(
        self,
        snapshot: TargetSceneSnapshot,
        observation: SpatialObservation,
    ) -> tuple[torch.Tensor, tuple[int, int, int, int]]:
        x1, y1, x2, y2 = snapshot.target.bbox_xyxy
        center_x = (x1 + x2) * 0.5
        center_y = (y1 + y2) * 0.5
        side = max(int(np.ceil(max(x2 - x1, y2 - y1) * self.config.crop_margin)), 32)
        crop_x1 = int(np.floor(center_x - side / 2.0))
        crop_y1 = int(np.floor(center_y - side / 2.0))
        crop = (crop_x1, crop_y1, crop_x1 + side, crop_y1 + side)

        target_depth = float(observation.target_depth.value)
        rgb_canvas = np.zeros((side, side, 3), dtype=np.uint8)
        depth_canvas = np.full((side, side), target_depth, dtype=np.float32)
        mask_canvas = np.zeros((side, side), dtype=np.uint8)
        height, width = snapshot.frame.rgb.shape[:2]
        src_x1 = max(crop_x1, 0)
        src_y1 = max(crop_y1, 0)
        src_x2 = min(crop_x1 + side, width)
        src_y2 = min(crop_y1 + side, height)
        dst_x1 = src_x1 - crop_x1
        dst_y1 = src_y1 - crop_y1
        dst_x2 = dst_x1 + (src_x2 - src_x1)
        dst_y2 = dst_y1 + (src_y2 - src_y1)
        rgb_canvas[dst_y1:dst_y2, dst_x1:dst_x2] = snapshot.frame.rgb[src_y1:src_y2, src_x1:src_x2]
        depth_source = np.asarray(observation.depth_frame.values, dtype=np.float32)
        depth_canvas[dst_y1:dst_y2, dst_x1:dst_x2] = depth_source[src_y1:src_y2, src_x1:src_x2]
        mask_canvas[dst_y1:dst_y2, dst_x1:dst_x2] = snapshot.target.mask[src_y1:src_y2, src_x1:src_x2]
        invalid_depth = ~np.isfinite(depth_canvas) | (depth_canvas <= 0.0)
        depth_canvas[invalid_depth] = target_depth

        size = self.config.input_size
        rgb = cv2.resize(rgb_canvas, (size, size), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        depth = cv2.resize(depth_canvas, (size, size), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        mask = cv2.resize(mask_canvas, (size, size), interpolation=cv2.INTER_NEAREST).astype(bool)
        # Suppress neighbouring objects while retaining the checkpoint's
        # original RGB-D normalization convention.
        rgb[~mask] = 0.0
        depth[~mask] = target_depth
        rgb -= float(np.mean(rgb))
        depth = np.clip(depth - float(np.mean(depth)), -1.0, 1.0)
        channels = np.concatenate((depth[None, ...], np.moveaxis(rgb, 2, 0)), axis=0)
        return torch.from_numpy(channels[None, ...].astype(np.float32)), crop

    def _restore_maps(
        self,
        snapshot: TargetSceneSnapshot,
        crop: tuple[int, int, int, int],
        quality: np.ndarray,
        angle: np.ndarray,
        width_px: np.ndarray,
        *,
        inference_time: float,
        model_load_time: float,
        model_was_ready: bool,
    ) -> GraspMaps:
        height, width = snapshot.frame.rgb.shape[:2]
        crop_x1, crop_y1, crop_x2, crop_y2 = crop
        side = crop_x2 - crop_x1
        restored_quality = np.zeros((height, width), dtype=np.float32)
        restored_angle = np.zeros((height, width), dtype=np.float32)
        restored_width = np.zeros((height, width), dtype=np.float32)
        resized_quality = cv2.resize(quality, (side, side), interpolation=cv2.INTER_LINEAR)
        resized_angle = cv2.resize(angle, (side, side), interpolation=cv2.INTER_LINEAR)
        resized_width = cv2.resize(width_px, (side, side), interpolation=cv2.INTER_LINEAR)
        resized_width *= side / float(self.config.input_size)
        src_x1 = max(crop_x1, 0)
        src_y1 = max(crop_y1, 0)
        src_x2 = min(crop_x2, width)
        src_y2 = min(crop_y2, height)
        local_x1 = src_x1 - crop_x1
        local_y1 = src_y1 - crop_y1
        local_x2 = local_x1 + (src_x2 - src_x1)
        local_y2 = local_y1 + (src_y2 - src_y1)
        target = snapshot.target.mask
        restored_quality[src_y1:src_y2, src_x1:src_x2] = resized_quality[local_y1:local_y2, local_x1:local_x2]
        restored_angle[src_y1:src_y2, src_x1:src_x2] = resized_angle[local_y1:local_y2, local_x1:local_x2]
        restored_width[src_y1:src_y2, src_x1:src_x2] = resized_width[local_y1:local_y2, local_x1:local_x2]
        restored_quality[~target] = 0.0
        restored_angle[~target] = 0.0
        restored_width[~target] = 0.0
        return GraspMaps(
            quality=restored_quality,
            angle=restored_angle,
            width_px=np.maximum(restored_width, 0.0),
            crop_xyxy=crop,
            model_input_size=(self.config.input_size, self.config.input_size),
            inference_time_s=inference_time,
            model_load_time_s=model_load_time,
            model_was_ready=model_was_ready,
            compute_device=str(self._device).upper(),
            model_location=str(self._model_location),
        )

    @staticmethod
    def _validate_inputs(snapshot: TargetSceneSnapshot, observation: SpatialObservation) -> None:
        if observation.snapshot_id != snapshot.snapshot_id:
            raise ValueError("SpatialObservation snapshot does not match target snapshot")
        if observation.source_frame_id != snapshot.frame.frame_id:
            raise ValueError("SpatialObservation frame does not match target snapshot")
        if observation.target_instance_id != snapshot.target.instance_id:
            raise ValueError("SpatialObservation target does not match target snapshot")
        shape = snapshot.frame.rgb.shape[:2]
        if observation.depth_frame.values.shape != shape or snapshot.target.mask.shape != shape:
            raise ValueError("RGB, target mask, and depth must share snapshot coordinates")

    @staticmethod
    def _emit(
        progress: GraspProgressCallback | None,
        stage: GraspStage,
        details: Mapping[str, object] | None = None,
    ) -> None:
        if progress is not None:
            progress(stage, details)

    @staticmethod
    @contextmanager
    def _legacy_module_aliases():
        names = (
            "inference",
            "inference.models",
            "inference.models.grasp_model",
            "inference.models.grconvnet3",
        )
        previous = {name: sys.modules.get(name) for name in names}
        inference = ModuleType("inference")
        models = ModuleType("inference.models")
        grasp_model = ModuleType("inference.models.grasp_model")
        grconvnet3 = ModuleType("inference.models.grconvnet3")
        grasp_model.GraspModel = GraspModel
        grasp_model.ResidualBlock = ResidualBlock
        grconvnet3.GenerativeResnet = GenerativeResnet
        inference.models = models
        models.grasp_model = grasp_model
        models.grconvnet3 = grconvnet3
        sys.modules.update(
            {
                "inference": inference,
                "inference.models": models,
                "inference.models.grasp_model": grasp_model,
                "inference.models.grconvnet3": grconvnet3,
            }
        )
        try:
            yield
        finally:
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
