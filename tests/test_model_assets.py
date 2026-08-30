from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

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

    def test_corrupt_release_bundle_is_rejected_instead_of_hidden_by_cache(self) -> None:
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
            resolver = ModelAssetResolver(
                release_model_roots=(bundle,),
                user_cache=cache,
            )
            with self.assertRaisesRegex(ModelAssetError, "release bundle"):
                resolver.resolve(asset, allow_download=False)

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


if __name__ == "__main__":
    unittest.main()
