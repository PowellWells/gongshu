from __future__ import annotations

from functools import partial
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from vision2grasp.model_assets import ModelAsset, ModelAssetResolver
from vision2grasp.target_perception import (
    FASTSAM_CACHE_ENV,
    FASTSAM_MODEL_ASSET,
    FastSAMChecksumError,
    FastSAMDownloadError,
    FastSAMModelLocation,
    FastSAMModelResolver,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FASTSAM = PROJECT_ROOT / "artifacts" / "models" / "FastSAM-s.pt"


class _PayloadHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, payload: bytes, status: int, **kwargs) -> None:
        self._payload = payload
        self._status = status
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        self.send_response(self._status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(self._payload)))
        self.end_headers()
        if self._status == 200:
            self.wfile.write(self._payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _ModelServer:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        handler = partial(_PayloadHandler, payload=payload, status=status)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}/FastSAM-s.pt"

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def fixture_asset(payload: bytes, url: str) -> ModelAsset:
    return ModelAsset(
        key="fastsam-fixture",
        relative_path=Path("fastsam") / "FastSAM-s.pt",
        url=url,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        source=url,
        revision="fixture",
        license="AGPL-3.0",
    )


class FastSAMModelResolverRegressionTests(unittest.TestCase):
    @unittest.skipUnless(PROJECT_FASTSAM.is_file(), "project FastSAM checkpoint missing")
    def test_a_project_compatible_checkpoint_runs_fully_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = FastSAMModelResolver(
                release_model_roots=(root / "empty-bundle",),
                project_compatible_paths=(PROJECT_FASTSAM,),
                user_cache=root / "empty-cache",
            ).resolve(FASTSAM_MODEL_ASSET, allow_download=False)
        self.assertEqual(result.location, FastSAMModelLocation.PROJECT_COMPATIBLE)
        self.assertEqual(result.path, PROJECT_FASTSAM)

    def test_b_verified_user_cache_is_used_when_local_paths_are_absent(self) -> None:
        payload = b"cached-fastsam"
        asset = fixture_asset(payload, "https://example.invalid/FastSAM-s.pt")
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            cached = cache / asset.relative_path
            cached.parent.mkdir(parents=True)
            cached.write_bytes(payload)
            result = FastSAMModelResolver(
                release_model_roots=(),
                project_compatible_paths=(),
                user_cache=cache,
            ).resolve(asset, allow_download=False)
        self.assertEqual(result.location, FastSAMModelLocation.USER_CACHE)

    def test_c_missing_model_downloads_and_is_verified(self) -> None:
        payload = b"official-download-fixture"
        with _ModelServer(payload) as url, tempfile.TemporaryDirectory() as temporary:
            asset = fixture_asset(payload, url)
            cache = Path(temporary) / "cache"
            result = FastSAMModelResolver(
                release_model_roots=(),
                project_compatible_paths=(),
                user_cache=cache,
            ).resolve(asset)
            self.assertEqual(result.location, FastSAMModelLocation.DOWNLOADED)
            self.assertEqual(result.path.read_bytes(), payload)

    def test_d_invalid_download_url_reports_download_failed_without_harming_files(self) -> None:
        payload = b"not-served"
        with _ModelServer(payload, status=404) as url, tempfile.TemporaryDirectory() as temporary:
            asset = fixture_asset(payload, url)
            cache = Path(temporary) / "cache"
            preserved = cache / "fastsam" / "preserved-valid-weight.pt"
            preserved.parent.mkdir(parents=True)
            preserved.write_bytes(b"preserve-me")
            resolver = FastSAMModelResolver(
                release_model_roots=(),
                project_compatible_paths=(),
                user_cache=cache,
            )
            with self.assertRaisesRegex(FastSAMDownloadError, "DOWNLOAD_FAILED") as raised:
                resolver.resolve(asset)
            self.assertEqual(raised.exception.code, "DOWNLOAD_FAILED")
            self.assertEqual(preserved.read_bytes(), b"preserve-me")
            self.assertFalse((cache / asset.relative_path).exists())

    def test_e_checksum_mismatch_is_rejected_without_falling_through(self) -> None:
        payload = b"expected-model"
        asset = fixture_asset(payload, "https://example.invalid/FastSAM-s.pt")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_model = root / "artifacts" / "models" / "FastSAM-s.pt"
            project_model.parent.mkdir(parents=True)
            project_model.write_bytes(b"tampered")
            cache = root / "cache"
            resolver = FastSAMModelResolver(
                release_model_roots=(),
                project_compatible_paths=(project_model,),
                user_cache=cache,
            )
            with self.assertRaisesRegex(FastSAMChecksumError, "CHECKSUM_FAILED") as raised:
                resolver.resolve(asset)
            self.assertEqual(raised.exception.code, "CHECKSUM_FAILED")
            self.assertFalse((cache / asset.relative_path).exists())

    def test_f_depth_and_fastsam_cache_configuration_are_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fastsam_cache = root / "fastsam-only"
            depth_cache = root / "depth-only"
            with patch.dict(
                os.environ,
                {
                    FASTSAM_CACHE_ENV: str(fastsam_cache),
                    "VISION2GRASP_MODEL_CACHE": str(depth_cache),
                },
            ):
                target_resolver = FastSAMModelResolver(
                    release_model_roots=(), project_compatible_paths=()
                )
                depth_resolver = ModelAssetResolver(release_model_roots=())
            self.assertEqual(target_resolver.user_cache, fastsam_cache)
            self.assertEqual(depth_resolver.user_cache, depth_cache)

    def test_resolution_order_is_bundle_then_project_then_cache(self) -> None:
        payload = b"same-verified-weight"
        asset = fixture_asset(payload, "https://example.invalid/FastSAM-s.pt")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            project = root / "artifacts" / "FastSAM-s.pt"
            cache = root / "cache"
            paths = (bundle / asset.relative_path, project, cache / asset.relative_path)
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            result = FastSAMModelResolver(
                release_model_roots=(bundle,),
                project_compatible_paths=(project,),
                user_cache=cache,
            ).resolve(asset, allow_download=False)
        self.assertEqual(result.location, FastSAMModelLocation.RELEASE_BUNDLE)


if __name__ == "__main__":
    unittest.main()
