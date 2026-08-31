"""Verified model lookup shared by source builds and self-contained releases."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
import os
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen
from uuid import uuid4


MODEL_CACHE_ENV = "VISION2GRASP_MODEL_CACHE"
RELEASE_BUNDLE_ENV = "VISION2GRASP_RELEASE_BUNDLE"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ModelAssetError(RuntimeError):
    """A required model is absent, corrupt, or could not be downloaded."""

    code = "MODEL_ASSET_ERROR"


class ModelLocation(str, Enum):
    RELEASE_BUNDLE = "RELEASE_BUNDLE"
    PROJECT_COMPATIBLE = "PROJECT_COMPATIBLE"
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
    diagnostics: tuple[Mapping[str, object], ...] = ()


ModelProgressCallback = Callable[[str, Mapping[str, object]], None]


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
    """Resolve bundle -> project compatibility -> cache -> verified download."""

    def __init__(
        self,
        *,
        release_model_roots: Iterable[Path] | None = None,
        project_compatible_paths: Iterable[Path] = (),
        user_cache: Path | None = None,
    ) -> None:
        roots = (
            default_release_model_roots()
            if release_model_roots is None
            else release_model_roots
        )
        self.release_model_roots = tuple(Path(path) for path in roots)
        self.project_compatible_paths = tuple(
            Path(path) for path in project_compatible_paths
        )
        self.user_cache = Path(user_cache or default_user_model_cache())

    def resolve(
        self,
        asset: ModelAsset,
        *,
        allow_download: bool = True,
        download_started: Callable[[], None] | None = None,
        progress: ModelProgressCallback | None = None,
    ) -> ResolvedModelAsset:
        diagnostics: list[dict[str, object]] = []
        self._emit(progress, "MODEL_RESOLVING", {"model_key": asset.key})
        for root in self.release_model_roots:
            candidate = root / asset.relative_path
            accepted = self._inspect_candidate(
                candidate,
                asset,
                ModelLocation.RELEASE_BUNDLE,
                diagnostics,
                progress,
            )
            if accepted is not None:
                return accepted

        for candidate in self.project_compatible_paths:
            accepted = self._inspect_candidate(
                candidate,
                asset,
                ModelLocation.PROJECT_COMPATIBLE,
                diagnostics,
                progress,
            )
            if accepted is not None:
                return accepted

        cached = self.user_cache / asset.relative_path
        accepted = self._inspect_candidate(
            cached,
            asset,
            ModelLocation.USER_CACHE,
            diagnostics,
            progress,
        )
        if accepted is not None:
            return accepted
        rejected_existing = [item for item in diagnostics if item["exists"]]
        cached_diagnostic = diagnostics[-1]
        if cached_diagnostic["exists"]:
            error = ModelAssetError(
                f"user cache model failed integrity validation: {cached}"
            )
            error.code = "CHECKSUM_FAILED"
            error.diagnostics = tuple(diagnostics)
            raise error
        if not allow_download:
            if rejected_existing:
                error = ModelAssetError(
                    f"no verified model candidate is usable: {asset.key}"
                )
                error.code = "CHECKSUM_FAILED"
            else:
                error = ModelAssetError(f"verified model is unavailable: {asset.key}")
                error.code = "MODEL_NOT_FOUND"
            error.diagnostics = tuple(diagnostics)
            raise error
        if download_started is not None:
            download_started()
        self._download_verified(asset, cached, progress=progress)
        selected = {
            "candidate_path": str(cached),
            "location": ModelLocation.DOWNLOADED.value,
            "exists": True,
            "size": asset.size_bytes,
            "expected_size": asset.size_bytes,
            "checksum_result": "MATCH",
            "accepted": True,
            "rejection_reason": None,
            "selected_source": ModelLocation.DOWNLOADED.value,
        }
        diagnostics.append(selected)
        self._emit(progress, "MODEL_RESOLVING", {"resolver_diagnostic": selected})
        return ResolvedModelAsset(
            asset,
            cached,
            ModelLocation.DOWNLOADED,
            tuple(diagnostics),
        )

    @classmethod
    def _inspect_candidate(
        cls,
        candidate: Path,
        asset: ModelAsset,
        location: ModelLocation,
        diagnostics: list[dict[str, object]],
        progress: ModelProgressCallback | None,
    ) -> ResolvedModelAsset | None:
        exists = candidate.is_file()
        diagnostic: dict[str, object] = {
            "candidate_path": str(candidate),
            "location": location.value,
            "exists": exists,
            "size": candidate.stat().st_size if exists else None,
            "expected_size": asset.size_bytes,
            "checksum_result": "NOT_CHECKED",
            "accepted": False,
            "rejection_reason": "NOT_FOUND" if not exists else None,
            "selected_source": None,
        }
        if not exists:
            diagnostics.append(diagnostic)
            cls._emit(progress, "MODEL_RESOLVING", {"resolver_diagnostic": diagnostic})
            return None
        if diagnostic["size"] != asset.size_bytes:
            diagnostic["rejection_reason"] = "SIZE_MISMATCH"
            diagnostics.append(diagnostic)
            cls._emit(progress, "MODEL_RESOLVING", {"resolver_diagnostic": diagnostic})
            return None
        cls._emit(
            progress,
            "CHECKSUM_VERIFYING",
            {
                "candidate_path": str(candidate),
                "bytes_total": asset.size_bytes,
                "location": location.value,
            },
        )
        digest = sha256_file(candidate)
        diagnostic["checksum_result"] = "MATCH" if digest == asset.sha256 else "MISMATCH"
        diagnostic["actual_sha256"] = digest
        if digest != asset.sha256:
            diagnostic["rejection_reason"] = "CHECKSUM_MISMATCH"
            diagnostics.append(diagnostic)
            cls._emit(progress, "CHECKSUM_VERIFYING", {"resolver_diagnostic": diagnostic})
            return None
        diagnostic["accepted"] = True
        diagnostic["selected_source"] = location.value
        diagnostics.append(diagnostic)
        cls._emit(progress, "CHECKSUM_VERIFYING", {"resolver_diagnostic": diagnostic})
        return ResolvedModelAsset(asset, candidate, location, tuple(diagnostics))

    @staticmethod
    def _download_verified(
        asset: ModelAsset,
        destination: Path,
        *,
        progress: ModelProgressCallback | None,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f"{destination.name}.download-{uuid4().hex}"
        )
        digest = hashlib.sha256()
        size = 0
        started = time.perf_counter()
        ModelAssetResolver._emit(
            progress,
            "MODEL_DOWNLOADING",
            {
                "bytes_downloaded": 0,
                "bytes_total": None,
                "download_progress": None,
            },
        )
        try:
            request = Request(
                asset.url,
                headers={"User-Agent": "Vision2Grasp-v0.5/1.0"},
            )
            with urlopen(request, timeout=120) as response, temporary.open("xb") as stream:
                content_length = response.headers.get("Content-Length")
                bytes_total = (
                    int(content_length)
                    if content_length and content_length.isdigit()
                    else None
                )
                ModelAssetResolver._emit(
                    progress,
                    "MODEL_DOWNLOADING",
                    {
                        "bytes_downloaded": 0,
                        "bytes_total": bytes_total,
                        "download_progress": 0.0 if bytes_total else None,
                    },
                )
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    stream.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    elapsed = max(time.perf_counter() - started, 1e-9)
                    speed = size / elapsed
                    ModelAssetResolver._emit(
                        progress,
                        "MODEL_DOWNLOADING",
                        {
                            "bytes_downloaded": size,
                            "bytes_total": bytes_total,
                            "download_progress": (
                                min(size / bytes_total, 1.0) if bytes_total else None
                            ),
                            "download_speed_bytes_s": speed,
                            "download_eta_s": (
                                max(bytes_total - size, 0) / speed
                                if bytes_total and speed > 0.0
                                else None
                            ),
                        },
                    )
            actual_digest = digest.hexdigest()
            ModelAssetResolver._emit(
                progress,
                "CHECKSUM_VERIFYING",
                {
                    "candidate_path": str(temporary),
                    "bytes_total": size,
                    "location": ModelLocation.DOWNLOADED.value,
                },
            )
            if size != asset.size_bytes or actual_digest != asset.sha256:
                error = ModelAssetError(
                    f"downloaded model failed integrity validation: {asset.key}; "
                    f"size={size}, sha256={actual_digest}"
                )
                error.code = "CHECKSUM_FAILED"
                raise error
            if destination.exists():
                if verify_model_file(destination, asset):
                    temporary.unlink(missing_ok=True)
                    return
                error = ModelAssetError(
                    f"refusing to overwrite existing invalid model: {destination}"
                )
                error.code = "CHECKSUM_FAILED"
                raise error
            os.link(temporary, destination)
            temporary.unlink()
        except Exception as error:
            temporary.unlink(missing_ok=True)
            if isinstance(error, ModelAssetError):
                raise
            wrapped = ModelAssetError(f"model download failed for {asset.key}: {error}")
            wrapped.code = "DOWNLOAD_FAILED"
            raise wrapped from error

    @staticmethod
    def _emit(
        progress: ModelProgressCallback | None,
        stage: str,
        details: Mapping[str, object],
    ) -> None:
        if progress is not None:
            progress(stage, details)
