"""FastSAM-specific verified model resolution for frozen v0.4 behavior."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4

from vision2grasp.model_assets import ModelAsset, default_release_model_roots, sha256_file


FASTSAM_CACHE_ENV = "VISION2GRASP_FASTSAM_CACHE"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FastSAMModelError(RuntimeError):
    """Base error carrying a stable user-visible model failure code."""

    code = "MODEL_LOAD_FAILED"

    def __init__(self, detail: str) -> None:
        super().__init__(f"{self.code}: {detail}")


class FastSAMModelNotFoundError(FastSAMModelError):
    code = "MODEL_NOT_FOUND"


class FastSAMDownloadError(FastSAMModelError):
    code = "DOWNLOAD_FAILED"


class FastSAMChecksumError(FastSAMModelError):
    code = "CHECKSUM_FAILED"


class FastSAMModelLoadError(FastSAMModelError):
    code = "MODEL_LOAD_FAILED"


class FastSAMModelLocation(str, Enum):
    RELEASE_BUNDLE = "RELEASE_BUNDLE"
    PROJECT_COMPATIBLE = "PROJECT_COMPATIBLE"
    USER_CACHE = "USER_CACHE"
    DOWNLOADED = "DOWNLOADED"


@dataclass(frozen=True, slots=True)
class ResolvedFastSAMModel:
    asset: ModelAsset
    path: Path
    location: FastSAMModelLocation


def default_fastsam_user_cache() -> Path:
    """Return FastSAM's cache root without consulting Depth's cache override."""

    override = os.environ.get(FASTSAM_CACHE_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "Vision2Grasp" / "model-cache"
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        return Path(xdg_cache) / "vision2grasp" / "models"
    return Path.home() / ".cache" / "vision2grasp" / "models"


def default_fastsam_project_paths() -> tuple[Path, ...]:
    """Keep the v0.4 source-tree checkpoint path as a first-class input."""

    return (_PROJECT_ROOT / "artifacts" / "models" / "FastSAM-s.pt",)


class FastSAMModelResolver:
    """Resolve bundle -> project compatibility -> FastSAM cache -> download."""

    def __init__(
        self,
        *,
        release_model_roots: Iterable[Path] | None = None,
        project_compatible_paths: Iterable[Path] | None = None,
        user_cache: Path | None = None,
    ) -> None:
        roots = (
            default_release_model_roots()
            if release_model_roots is None
            else release_model_roots
        )
        project_paths = (
            default_fastsam_project_paths()
            if project_compatible_paths is None
            else project_compatible_paths
        )
        self.release_model_roots = tuple(Path(path) for path in roots)
        self.project_compatible_paths = tuple(Path(path) for path in project_paths)
        self.user_cache = Path(user_cache or default_fastsam_user_cache())

    def resolve(
        self,
        asset: ModelAsset,
        *,
        allow_download: bool = True,
        download_started: Callable[[], None] | None = None,
    ) -> ResolvedFastSAMModel:
        for root in self.release_model_roots:
            candidate = root / asset.relative_path
            if candidate.exists():
                self._verify_existing(candidate, asset, "release bundle")
                return ResolvedFastSAMModel(
                    asset, candidate, FastSAMModelLocation.RELEASE_BUNDLE
                )

        for candidate in self.project_compatible_paths:
            if candidate.exists():
                self._verify_existing(candidate, asset, "project-compatible")
                return ResolvedFastSAMModel(
                    asset, candidate, FastSAMModelLocation.PROJECT_COMPATIBLE
                )

        cached = self.user_cache / asset.relative_path
        if cached.exists():
            self._verify_existing(cached, asset, "user cache")
            return ResolvedFastSAMModel(asset, cached, FastSAMModelLocation.USER_CACHE)

        if not allow_download:
            raise FastSAMModelNotFoundError(
                f"verified FastSAM checkpoint is unavailable: {asset.key}"
            )
        if download_started is not None:
            download_started()
        self._download_verified(asset, cached)
        return ResolvedFastSAMModel(asset, cached, FastSAMModelLocation.DOWNLOADED)

    @staticmethod
    def _verify_existing(path: Path, asset: ModelAsset, location: str) -> None:
        candidate = Path(path)
        size = candidate.stat().st_size
        digest = sha256_file(candidate)
        if size != asset.size_bytes or digest != asset.sha256:
            raise FastSAMChecksumError(
                f"{location} checkpoint failed integrity validation: {candidate}; "
                f"expected size={asset.size_bytes}, sha256={asset.sha256}; "
                f"got size={size}, sha256={digest}"
            )

    @staticmethod
    def _download_verified(asset: ModelAsset, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f"{destination.name}.download-{uuid4().hex}"
        )
        digest = hashlib.sha256()
        size = 0
        try:
            request = Request(
                asset.url,
                headers={"User-Agent": "Vision2Grasp-FastSAM-v0.4/1.0"},
            )
            with urlopen(request, timeout=120) as response, temporary.open("xb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    stream.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            raise FastSAMDownloadError(
                f"official checkpoint download failed for {asset.key}: {error}"
            ) from error

        actual_digest = digest.hexdigest()
        if size != asset.size_bytes or actual_digest != asset.sha256:
            temporary.unlink(missing_ok=True)
            raise FastSAMChecksumError(
                f"downloaded checkpoint failed integrity validation: {asset.key}; "
                f"expected size={asset.size_bytes}, sha256={asset.sha256}; "
                f"got size={size}, sha256={actual_digest}"
            )

        # Never replace a pre-existing file. A concurrent valid download wins;
        # a concurrent invalid file is reported and left untouched for diagnosis.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            temporary.unlink(missing_ok=True)
            FastSAMModelResolver._verify_existing(destination, asset, "user cache")
            return
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise FastSAMDownloadError(
                f"verified checkpoint could not be installed in user cache: {error}"
            ) from error
        temporary.unlink()
