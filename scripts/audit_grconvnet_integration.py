"""Developer-only GR-ConvNet checkpoint and preprocessing audit.

The command prints JSON to stdout and never writes captures or model output.
It intentionally mirrors the preprocessing at the pinned upstream revision:

* RGB: resize, convert to [0, 1], subtract the global RGB mean.
* Depth: subtract the global mean, clip to [-1, 1], then resize.
* Model input: [depth, red, green, blue], float32, NCHW.
* Width postprocess: multiply the raw head by the upstream constant 150.

Example:
    python scripts/audit_grconvnet_integration.py --jacquard-root C:\\...\\Samples
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from skimage.filters import gaussian
from skimage.transform import resize
import torch

from vision2grasp.grasp_planning.detector import GRConvNetDetector


UPSTREAM_INPUT_SIZE = 224
UPSTREAM_WIDTH_POSTPROCESS_SCALE = 150.0
TRAINING_WIDTH_LABEL_SCALE = UPSTREAM_INPUT_SIZE / 2.0


def _range(values: np.ndarray) -> list[float]:
    return [float(np.min(values)), float(np.max(values))]


def _stats(values: np.ndarray) -> dict[str, Any]:
    finite = np.asarray(values)[np.isfinite(values)]
    if finite.size == 0:
        return {"shape": list(values.shape), "dtype": str(values.dtype), "finite": 0}
    return {
        "shape": list(values.shape),
        "dtype": str(values.dtype),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "mean": float(np.mean(finite)),
        "p50": float(np.percentile(finite, 50.0)),
        "p95": float(np.percentile(finite, 95.0)),
        "p99": float(np.percentile(finite, 99.0)),
        "finite": int(finite.size),
    }


def _upstream_resize(values: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    return resize(values, shape, preserve_range=True).astype(values.dtype)


def prepare_official_jacquard(
    rgb_path: Path,
    depth_path: Path,
) -> tuple[torch.Tensor, dict[str, Any]]:
    # Upstream imageio.imread uses the same Pillow-backed decoding for these
    # PNG/TIFF samples; using Pillow directly avoids adding a runtime package.
    with Image.open(rgb_path) as image:
        rgb_crop = np.asarray(image).copy()
    with Image.open(depth_path) as image:
        depth_crop = np.asarray(image).copy()
    if rgb_crop.ndim != 3 or rgb_crop.shape[2] != 3:
        raise ValueError(f"expected RGB HWC image, got {rgb_crop.shape}")
    if depth_crop.ndim != 2:
        raise ValueError(f"expected scalar depth image, got {depth_crop.shape}")

    # Exact ordering from JacquardDataset at upstream commit 183c6f68:
    # depth is normalised before resize; RGB is resized before normalisation.
    depth = np.clip(depth_crop - float(np.mean(depth_crop)), -1.0, 1.0)
    depth = _upstream_resize(depth, (UPSTREAM_INPUT_SIZE, UPSTREAM_INPUT_SIZE))
    rgb = _upstream_resize(
        rgb_crop,
        (UPSTREAM_INPUT_SIZE, UPSTREAM_INPUT_SIZE, 3),
    )
    rgb = rgb.astype(np.float32) / 255.0
    rgb -= float(np.mean(rgb))
    channels = np.concatenate((depth[None, ...], np.moveaxis(rgb, 2, 0)), axis=0)
    tensor = torch.from_numpy(channels[None, ...].astype(np.float32))
    diagnostics = {
        "rgb_crop": _stats(rgb_crop),
        "depth_crop": _stats(depth_crop),
        "normalized_rgb": _stats(rgb),
        "normalized_depth": _stats(depth),
        "model_input": _stats(tensor.numpy()),
        "model_input_channel_order": ["depth", "red", "green", "blue"],
        "rgb_channel_order": "RGB",
        "depth_source": "perfect_depth.tiff numeric tensor",
        "preprocessing": "PINNED_UPSTREAM_JACQUARD",
    }
    return tensor, diagnostics


def _target_square_crop(
    rgb: np.ndarray,
    depth: np.ndarray,
    mask: np.ndarray,
    margin: float = 1.35,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[int]]:
    rows, columns = np.nonzero(mask)
    if rows.size == 0:
        raise ValueError("target mask is empty")
    x1, x2 = int(columns.min()), int(columns.max()) + 1
    y1, y2 = int(rows.min()), int(rows.max()) + 1
    side = max(int(np.ceil(max(x2 - x1, y2 - y1) * margin)), 32)
    center_x = (x1 + x2) * 0.5
    center_y = (y1 + y2) * 0.5
    crop_x1 = int(np.floor(center_x - side / 2.0))
    crop_y1 = int(np.floor(center_y - side / 2.0))
    crop_x2 = crop_x1 + side
    crop_y2 = crop_y1 + side
    if crop_x1 < 0 or crop_y1 < 0 or crop_x2 > rgb.shape[1] or crop_y2 > rgb.shape[0]:
        raise ValueError("sample target crop crosses the image boundary")
    return (
        rgb[crop_y1:crop_y2, crop_x1:crop_x2].copy(),
        depth[crop_y1:crop_y2, crop_x1:crop_x2].copy(),
        mask[crop_y1:crop_y2, crop_x1:crop_x2].copy(),
        [crop_x1, crop_y1, crop_x2, crop_y2],
    )


def prepare_target_crop_ab(
    rgb_path: Path,
    depth_path: Path,
    mask_path: Path,
) -> dict[str, tuple[torch.Tensor, dict[str, Any]]]:
    with Image.open(rgb_path) as image:
        rgb = np.asarray(image).copy()
    with Image.open(depth_path) as image:
        depth = np.asarray(image).copy()
    with Image.open(mask_path) as image:
        raw_mask = np.asarray(image).copy()
    mask = raw_mask if raw_mask.ndim == 2 else np.any(raw_mask != 0, axis=2)
    mask = mask.astype(bool)
    rgb_crop, depth_crop, mask_crop, crop = _target_square_crop(rgb, depth, mask)
    target_depth = float(np.median(depth_crop[mask_crop]))
    invalid = ~np.isfinite(depth_crop) | (depth_crop <= 0.0)
    depth_crop[invalid] = target_depth

    # A: exact current Gongshu operation ordering and OpenCV interpolation.
    current_rgb = cv2.resize(
        rgb_crop,
        (UPSTREAM_INPUT_SIZE, UPSTREAM_INPUT_SIZE),
        interpolation=cv2.INTER_LINEAR,
    ).astype(np.float32) / 255.0
    current_depth = cv2.resize(
        depth_crop,
        (UPSTREAM_INPUT_SIZE, UPSTREAM_INPUT_SIZE),
        interpolation=cv2.INTER_LINEAR,
    ).astype(np.float32)
    current_mask = cv2.resize(
        mask_crop.astype(np.uint8),
        (UPSTREAM_INPUT_SIZE, UPSTREAM_INPUT_SIZE),
        interpolation=cv2.INTER_NEAREST,
    ).astype(bool)
    current_rgb[~current_mask] = 0.0
    current_depth[~current_mask] = target_depth
    current_rgb -= float(np.mean(current_rgb))
    current_depth = np.clip(current_depth - float(np.mean(current_depth)), -1.0, 1.0)
    current_channels = np.concatenate(
        (current_depth[None, ...], np.moveaxis(current_rgb, 2, 0)), axis=0
    )

    # B: same target crop and invalid-depth fill, but strict upstream ordering,
    # no target-mask suppression, and skimage resize semantics.
    official_depth = np.clip(depth_crop - float(np.mean(depth_crop)), -1.0, 1.0)
    official_depth = _upstream_resize(
        official_depth,
        (UPSTREAM_INPUT_SIZE, UPSTREAM_INPUT_SIZE),
    )
    official_rgb = _upstream_resize(
        rgb_crop,
        (UPSTREAM_INPUT_SIZE, UPSTREAM_INPUT_SIZE, 3),
    ).astype(np.float32) / 255.0
    official_rgb -= float(np.mean(official_rgb))
    official_channels = np.concatenate(
        (official_depth[None, ...], np.moveaxis(official_rgb, 2, 0)), axis=0
    )

    common = {
        "crop_xyxy": crop,
        "target_depth_median": target_depth,
        "rgb_crop": _stats(rgb_crop),
        "depth_crop": _stats(depth_crop),
        "mask_fraction": float(np.mean(mask_crop)),
        "model_input_channel_order": ["depth", "red", "green", "blue"],
    }
    return {
        "gongshu_current": (
            torch.from_numpy(current_channels[None, ...].astype(np.float32)),
            {
                **common,
                "normalized_rgb": _stats(current_rgb),
                "normalized_depth": _stats(current_depth),
                "model_input": _stats(current_channels[None, ...]),
                "preprocessing": "GONGSHU_MASK_SUPPRESSED",
            },
        ),
        "official_same_crop": (
            torch.from_numpy(official_channels[None, ...].astype(np.float32)),
            {
                **common,
                "normalized_rgb": _stats(official_rgb),
                "normalized_depth": _stats(official_depth),
                "model_input": _stats(official_channels[None, ...]),
                "preprocessing": "PINNED_UPSTREAM_SAME_TARGET_CROP",
            },
        ),
    }


def infer_tensor(detector: GRConvNetDetector, tensor: torch.Tensor) -> dict[str, Any]:
    if not detector.model_ready:
        detector._load(None)  # Developer audit of the same verified runtime asset.
    assert detector._model is not None and detector._device is not None
    with torch.inference_mode():
        outputs = detector._model(tensor.to(detector._device))
    position, cosine, sine, width = outputs
    raw_quality = position.detach().float().cpu().numpy().squeeze()
    raw_cosine = cosine.detach().float().cpu().numpy().squeeze()
    raw_sine = sine.detach().float().cpu().numpy().squeeze()
    raw_width = width.detach().float().cpu().numpy().squeeze()
    raw_angle = np.arctan2(raw_sine, raw_cosine) / 2.0

    quality = gaussian(raw_quality, 2.0, preserve_range=True)
    angle = gaussian(raw_angle, 2.0, preserve_range=True)
    upstream_width = gaussian(
        raw_width * UPSTREAM_WIDTH_POSTPROCESS_SCALE,
        1.0,
        preserve_range=True,
    )
    label_inverse_width = gaussian(
        raw_width * TRAINING_WIDTH_LABEL_SCALE,
        1.0,
        preserve_range=True,
    )
    return {
        "raw_quality": _stats(raw_quality),
        "postprocessed_quality": _stats(quality),
        "raw_width_head": _stats(raw_width),
        "postprocessed_width_px_upstream_x150": _stats(upstream_width),
        "postprocessed_width_px_training_label_inverse_x112": _stats(label_inverse_width),
        "raw_angle_rad": _stats(raw_angle),
        "postprocessed_angle_rad": _stats(angle),
        "raw_cosine": _stats(raw_cosine),
        "raw_sine": _stats(raw_sine),
    }


def _sample_pairs(root: Path, limit: int | None) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for rgb_path in sorted(root.rglob("*_RGB.png")):
        depth_path = rgb_path.with_name(rgb_path.name.replace("_RGB.png", "_perfect_depth.tiff"))
        if depth_path.is_file():
            pairs.append((rgb_path, depth_path))
        if limit is not None and len(pairs) >= limit:
            break
    if not pairs:
        raise FileNotFoundError(f"no Jacquard RGB/perfect-depth pairs below {root}")
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jacquard-root", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()

    detector = GRConvNetDetector()
    if args.device != "auto":
        from vision2grasp.grasp_planning.detector import GRConvNetDetectorConfig

        detector = GRConvNetDetector(GRConvNetDetectorConfig(device=args.device))

    samples: list[dict[str, Any]] = []
    for rgb_path, depth_path in _sample_pairs(args.jacquard_root, args.limit):
        tensor, input_diagnostics = prepare_official_jacquard(rgb_path, depth_path)
        outputs = infer_tensor(detector, tensor)
        mask_path = rgb_path.with_name(rgb_path.name.replace("_RGB.png", "_mask.png"))
        crop_ab: dict[str, Any] = {}
        if mask_path.is_file():
            try:
                prepared_ab = prepare_target_crop_ab(rgb_path, depth_path, mask_path)
            except ValueError as error:
                crop_ab["skipped"] = {"reason": str(error)}
            else:
                for name, (crop_tensor, crop_input) in prepared_ab.items():
                    crop_ab[name] = {
                        "input": crop_input,
                        "output": infer_tensor(detector, crop_tensor),
                    }
        samples.append(
            {
                "sample": rgb_path.stem.removesuffix("_RGB"),
                "input": input_diagnostics,
                "output": outputs,
                "target_crop_ab": crop_ab,
            }
        )

    quality_maxima = np.asarray(
        [sample["output"]["postprocessed_quality"]["max"] for sample in samples]
    )
    width_maxima = np.asarray(
        [
            sample["output"]["postprocessed_width_px_upstream_x150"]["max"]
            for sample in samples
        ]
    )
    crop_ab_aggregate: dict[str, Any] = {}
    for name in ("gongshu_current", "official_same_crop"):
        available = [sample["target_crop_ab"].get(name) for sample in samples]
        available = [item for item in available if item is not None]
        if available:
            crop_ab_aggregate[name] = {
                "sample_count": len(available),
                "quality_maxima": _stats(
                    np.asarray(
                        [item["output"]["postprocessed_quality"]["max"] for item in available]
                    )
                ),
                "upstream_width_px_maxima": _stats(
                    np.asarray(
                        [
                            item["output"]["postprocessed_width_px_upstream_x150"]["max"]
                            for item in available
                        ]
                    )
                ),
            }
    report = {
        "checkpoint": {
            "device": detector.compute_device,
            "model_location": detector._model_location,
            "input_size": [UPSTREAM_INPUT_SIZE, UPSTREAM_INPUT_SIZE],
            "input_channel_order": ["depth", "red", "green", "blue"],
            "upstream_width_postprocess_scale": UPSTREAM_WIDTH_POSTPROCESS_SCALE,
            "training_width_label_scale": TRAINING_WIDTH_LABEL_SCALE,
        },
        "aggregate": {
            "sample_count": len(samples),
            "quality_maxima": _stats(quality_maxima),
            "upstream_width_px_maxima": _stats(width_maxima),
            "target_crop_ab": crop_ab_aggregate,
        },
        "samples": samples,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
