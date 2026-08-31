from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vision2grasp.model_assets import (
    ModelAsset,
    ModelAssetError,
    ModelAssetResolver,
    ModelLocation,
)


class ModelAssetResolverTests(unittest.TestCase):
    @staticmethod
    def asset(payload: bytes) -> ModelAsset:
        return ModelAsset(
            key="fixture",
            relative_path=Path("fixture") / "model.pth",
            url="https://example.invalid/model.pth",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            source="https://example.invalid",
            revision="fixture-revision",
            license="Apache-2.0",
        )

    def test_release_bundle_precedes_user_cache(self) -> None:
        payload = b"verified-model-payload"
        asset = self.asset(payload)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle-models"
            cache = root / "cache"
            for model_root in (bundle, cache):
                path = model_root / asset.relative_path
                path.parent.mkdir(parents=True)
                path.write_bytes(payload)
            resolved = ModelAssetResolver(
                release_model_roots=(bundle,),
                user_cache=cache,
            ).resolve(asset, allow_download=False)
            self.assertEqual(resolved.location, ModelLocation.RELEASE_BUNDLE)
            self.assertEqual(resolved.path, bundle / asset.relative_path)

    def test_corrupt_release_bundle_is_diagnosed_then_valid_cache_is_used(self) -> None:
        payload = b"verified-model-payload"
        asset = self.asset(payload)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle-models"
            cache = root / "cache"
            bundle_path = bundle / asset.relative_path
            cache_path = cache / asset.relative_path
            bundle_path.parent.mkdir(parents=True)
            cache_path.parent.mkdir(parents=True)
            bundle_path.write_bytes(b"corrupt")
            cache_path.write_bytes(payload)
            resolved = ModelAssetResolver(
                release_model_roots=(bundle,),
                user_cache=cache,
            ).resolve(asset, allow_download=False)
            self.assertEqual(resolved.location, ModelLocation.USER_CACHE)
            self.assertEqual(resolved.diagnostics[0]["rejection_reason"], "SIZE_MISMATCH")
            self.assertTrue(resolved.diagnostics[-1]["accepted"])

    def test_user_cache_is_used_offline_when_bundle_is_absent(self) -> None:
        payload = b"verified-model-payload"
        asset = self.asset(payload)
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            path = cache / asset.relative_path
            path.parent.mkdir(parents=True)
            path.write_bytes(payload)
            resolved = ModelAssetResolver(
                release_model_roots=(),
                user_cache=cache,
            ).resolve(asset, allow_download=False)
            self.assertEqual(resolved.location, ModelLocation.USER_CACHE)

    def test_stale_partial_is_diagnostic_evidence_not_a_model_candidate(self) -> None:
        payload = b"verified-model-payload"
        asset = self.asset(payload)
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            path = cache / asset.relative_path
            path.parent.mkdir(parents=True)
            path.write_bytes(payload)
            path.with_suffix(".pth.download").write_bytes(payload[:5])
            resolved = ModelAssetResolver(
                release_model_roots=(),
                user_cache=cache,
            ).resolve(asset, allow_download=False)
            self.assertEqual(resolved.path, path)
            self.assertEqual(resolved.location, ModelLocation.USER_CACHE)
            self.assertTrue(resolved.diagnostics[-1]["accepted"])

    def test_corrupt_cache_is_never_loaded_or_overwritten(self) -> None:
        payload = b"verified-model-payload"
        asset = self.asset(payload)
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            path = cache / asset.relative_path
            path.parent.mkdir(parents=True)
            path.write_bytes(b"corrupt")
            with self.assertRaises(ModelAssetError) as raised:
                ModelAssetResolver(
                    release_model_roots=(),
                    user_cache=cache,
                ).resolve(asset, allow_download=True)
            self.assertEqual(raised.exception.code, "CHECKSUM_FAILED")
            self.assertEqual(path.read_bytes(), b"corrupt")

    def test_missing_model_downloads_to_verified_cache_with_real_progress(self) -> None:
        payload = b"verified-model-payload"
        asset = self.asset(payload)

        class _Response(io.BytesIO):
            headers = {"Content-Length": str(len(payload))}

        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            events: list[tuple[str, dict[str, object]]] = []
            with patch(
                "vision2grasp.model_assets.urlopen", return_value=_Response(payload)
            ):
                resolved = ModelAssetResolver(
                    release_model_roots=(), user_cache=cache
                ).resolve(
                    asset,
                    progress=lambda stage, details: events.append(
                        (stage, dict(details))
                    ),
                )
            self.assertEqual(resolved.location, ModelLocation.DOWNLOADED)
            self.assertEqual(resolved.path.read_bytes(), payload)
            stages = [stage for stage, _details in events]
            self.assertIn("MODEL_DOWNLOADING", stages)
            self.assertIn("CHECKSUM_VERIFYING", stages)
            known_total = [
                details
                for stage, details in events
                if stage == "MODEL_DOWNLOADING" and details.get("bytes_total")
            ]
            self.assertTrue(known_total)
            self.assertEqual(known_total[-1]["download_progress"], 1.0)

    def test_download_connection_failure_reports_download_failed(self) -> None:
        payload = b"verified-model-payload"
        asset = self.asset(payload)
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary) / "cache"
            events: list[str] = []
            with patch(
                "vision2grasp.model_assets.urlopen",
                side_effect=OSError("fixture endpoint unavailable"),
            ):
                with self.assertRaises(ModelAssetError) as raised:
                    ModelAssetResolver(
                        release_model_roots=(), user_cache=cache
                    ).resolve(
                        asset,
                        progress=lambda stage, _details: events.append(stage),
                    )
            self.assertEqual(raised.exception.code, "DOWNLOAD_FAILED")
            self.assertIn("MODEL_DOWNLOADING", events)
            self.assertFalse((cache / asset.relative_path).exists())


if __name__ == "__main__":
    unittest.main()
