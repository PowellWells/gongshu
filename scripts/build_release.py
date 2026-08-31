"""Verify models and package a prepared self-contained Windows application."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from vision2grasp.model_assets import ModelAsset, ModelAssetResolver, sha256_file
from vision2grasp.grasp_planning import (
    GRCONVNET_MODEL_ASSET,
    GRCONVNET_PROJECT_COMPATIBLE_PATHS,
)
from vision2grasp.spatial_perception import (
    DEPTH_MODEL_ASSET,
    DEPTH_PROJECT_COMPATIBLE_PATHS,
)
from vision2grasp.target_perception import FASTSAM_MODEL_ASSET, FastSAMModelResolver


REQUIRED_MODELS = (FASTSAM_MODEL_ASSET, DEPTH_MODEL_ASSET, GRCONVNET_MODEL_ASSET)
REQUIRED_SOURCE_DEPENDENCIES = (
    "cv2",
    "numpy",
    "PySide6",
    "torch",
    "torchvision",
    "ultralytics",
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def check_source_dependencies() -> dict[str, bool]:
    return {
        package: importlib.util.find_spec(package) is not None
        for package in REQUIRED_SOURCE_DEPENDENCIES
    }


def resolve_required_models(
    resolver: ModelAssetResolver,
    *,
    allow_download: bool,
    fastsam_resolver: FastSAMModelResolver | None = None,
) -> tuple[tuple[ModelAsset, Path, str], ...]:
    resolved = []
    for asset in REQUIRED_MODELS:
        if asset == FASTSAM_MODEL_ASSET:
            target_resolver = fastsam_resolver or FastSAMModelResolver()
            result = target_resolver.resolve(asset, allow_download=allow_download)
        else:
            result = resolver.resolve(asset, allow_download=allow_download)
        resolved.append((asset, result.path, result.location.value))
    return tuple(resolved)


def model_manifest(
    models: tuple[tuple[ModelAsset, Path, str], ...],
) -> dict[str, object]:
    return {
        "schema_version": "vision2grasp.release-models/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookup_priority": {
            FASTSAM_MODEL_ASSET.key: [
                "RELEASE_BUNDLE",
                "PROJECT_COMPATIBLE",
                "USER_CACHE",
                "NETWORK_DOWNLOAD",
            ],
            DEPTH_MODEL_ASSET.key: [
                "RELEASE_BUNDLE",
                "PROJECT_COMPATIBLE",
                "USER_CACHE",
                "NETWORK_DOWNLOAD",
            ],
            GRCONVNET_MODEL_ASSET.key: [
                "RELEASE_BUNDLE",
                "PROJECT_COMPATIBLE",
                "USER_CACHE",
                "NETWORK_DOWNLOAD",
            ],
        },
        "models": [
            {
                **{
                    key: (str(value) if isinstance(value, Path) else value)
                    for key, value in asdict(asset).items()
                },
                "bundle_path": str(Path("models") / asset.relative_path).replace("\\", "/"),
                "build_source": location,
                "verified_sha256": sha256_file(path),
            }
            for asset, path, location in models
        ],
    }


def _validate_prepared_app(path: Path) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"prepared Windows app directory not found: {path}")
    has_launcher = any(path.glob("*.exe")) or (path / "run_vision2grasp_app.py").is_file()
    if not has_launcher:
        raise ValueError("prepared app must contain a Windows executable or source launcher")
    if not (path / "frontend").is_dir():
        raise ValueError("prepared app must contain the frontend directory")


def build_release_zip(
    *,
    prepared_app: Path,
    output_zip: Path,
    resolver: ModelAssetResolver,
    fastsam_resolver: FastSAMModelResolver | None = None,
    allow_download: bool = True,
) -> Path:
    prepared_app = prepared_app.resolve()
    output_zip = output_zip.resolve()
    _validate_prepared_app(prepared_app)
    models = resolve_required_models(
        resolver,
        allow_download=allow_download,
        fastsam_resolver=fastsam_resolver,
    )
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="vision2grasp-release-") as temporary:
        stage = Path(temporary) / "Vision2Grasp"
        shutil.copytree(prepared_app, stage)
        for asset, source, _location in models:
            destination = stage / "models" / asset.relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if sha256_file(destination) != asset.sha256:
                raise RuntimeError(f"bundled model verification failed: {asset.key}")
        shutil.copy2(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md", stage / "THIRD_PARTY_NOTICES.md")
        manifest = model_manifest(models)
        (stage / "release-models.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(stage.parent))
    return output_zip


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify runtime dependencies and model assets, then add verified models "
            "to a prepared self-contained Windows app and generate a ZIP."
        )
    )
    parser.add_argument("--prepared-app", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--offline", action="store_true", help="forbid network downloads")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dependencies = check_source_dependencies()
    missing = sorted(name for name, available in dependencies.items() if not available)
    if missing:
        raise RuntimeError(f"release dependency check failed: {', '.join(missing)}")
    resolver = ModelAssetResolver(
        project_compatible_paths=(
            *DEPTH_PROJECT_COMPATIBLE_PATHS,
            *GRCONVNET_PROJECT_COMPATIBLE_PATHS,
        )
    )
    fastsam_resolver = FastSAMModelResolver()
    models = resolve_required_models(
        resolver,
        allow_download=not args.offline,
        fastsam_resolver=fastsam_resolver,
    )
    print(json.dumps(model_manifest(models), ensure_ascii=False, indent=2))
    if args.verify_only:
        return 0
    if args.prepared_app is None or args.output is None:
        raise ValueError("--prepared-app and --output are required unless --verify-only is used")
    output = build_release_zip(
        prepared_app=args.prepared_app,
        output_zip=args.output,
        resolver=resolver,
        fastsam_resolver=fastsam_resolver,
        allow_download=not args.offline,
    )
    print(f"Windows release ZIP: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
