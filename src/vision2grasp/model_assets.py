"""Verified model lookup shared by source builds and self-contained releases."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen


MODEL_CACHE_ENV = "VISION2GRASP_MODEL_CACHE"
RELEASE_BUNDLE_ENV = "VISION2GRASP_RELEASE_BUNDLE"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ModelAssetError(RuntimeError):
    """A required model is absent, corrupt, or could not be downloaded."""


class ModelLocation(str, Enum):
    RELEASE_BUNDLE = "RELEASE_BUNDLE"
    USER_CACHE = "USER_CACHE"
    DOWNLOADED = "DOWNLOADED"


@dataclass(frozen=True, slots=True)
class ModelAsset:
    key: str
    relative_path: Path
    url: str
    size_bytes: int
    sha256: str
    source: str
    revision: str
    license: str

    def __post_init__(self) -> None:
        relative = Path(self.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("model relative_path must stay inside a model root")
        digest = self.sha256.strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("model sha256 must be a hexadecimal SHA-256 digest")
        if self.size_bytes <= 0:
            raise ValueError("model size_bytes must be positive")
        object.__setattr__(self, "relative_path", relative)
        object.__setattr__(self, "sha256", digest)


@dataclass(frozen=True, slots=True)
class ResolvedModelAsset:
    asset: ModelAsset
    path: Path
    location: ModelLocation


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_file(path: Path, asset: ModelAsset) -> bool:
    candidate = Path(path)
    return (
        candidate.is_file()
        and candidate.stat().st_size == asset.size_bytes
        and sha256_file(candidate) == asset.sha256
    )


def default_user_model_cache() -> Path:
    override = os.environ.get(MODEL_CACHE_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "Vision2Grasp" / "model-cache"
    xdg_cache = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg_cache:
        return Path(xdg_cache) / "vision2grasp" / "models"
    return Path.home() / ".cache" / "vision2grasp" / "models"


def default_release_model_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    override = os.environ.get(RELEASE_BUNDLE_ENV, "").strip()
    if override:
        roots.append(Path(override).expanduser().resolve() / "models")
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent / "models")
    roots.append(_PROJECT_ROOT / "models")
    return tuple(dict.fromkeys(roots))


class ModelAssetResolver:
    """Resolve bundle -> user cache -> verified download, in that order."""

    def __init__(
        self,
        *,
        release_model_roots: Iterable[Path] | None = None,
        user_cache: Path | None = None,
    ) -> None:
        roots = (
            default_release_model_roots()
            if release_model_roots is None
            else release_model_roots
        )
        self.release_model_roots = tuple(Path(path) for path in roots)
        self.user_cache = Path(user_cache or default_user_model_cache())

    def resolve(
        self,
        asset: ModelAsset,
        *,
        allow_download: bool = True,
        download_started: Callable[[], None] | None = None,
    ) -> ResolvedModelAsset:
        for root in self.release_model_roots:
            candidate = root / asset.relative_path
            if not candidate.exists():
                continue
            if not verify_model_file(candidate, asset):
                raise ModelAssetError(
                    f"release bundle model failed SHA-256 validation: {asset.key}"
                )
            return ResolvedModelAsset(asset, candidate, ModelLocation.RELEASE_BUNDLE)

        cached = self.user_cache / asset.relative_path
        if verify_model_file(cached, asset):
            return ResolvedModelAsset(asset, cached, ModelLocation.USER_CACHE)
        if not allow_download:
            raise ModelAssetError(f"verified model is unavailable: {asset.key}")
        if download_started is not None:
            download_started()
        self._download_verified(asset, cached)
        return ResolvedModelAsset(asset, cached, ModelLocation.DOWNLOADED)

    @staticmethod
    def _download_verified(asset: ModelAsset, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".download")
        digest = hashlib.sha256()
        size = 0
        try:
            request = Request(
                asset.url,
                headers={"User-Agent": "Vision2Grasp-v0.5/1.0"},
            )
            with urlopen(request, timeout=120) as response, temporary.open("wb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    stream.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            actual_digest = digest.hexdigest()
            if size != asset.size_bytes or actual_digest != asset.sha256:
                raise ModelAssetError(
                    f"downloaded model failed integrity validation: {asset.key}; "
                    f"size={size}, sha256={actual_digest}"
                )
            temporary.replace(destination)
        except Exception as error:
            temporary.unlink(missing_ok=True)
            if isinstance(error, ModelAssetError):
                raise
            raise ModelAssetError(f"model download failed for {asset.key}: {error}") from error
