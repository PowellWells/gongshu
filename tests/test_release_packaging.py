from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.build_release import build_release_zip
from vision2grasp.model_assets import ModelAsset, ModelAssetResolver


class ReleasePackagingTests(unittest.TestCase):
    def test_prepared_windows_app_receives_verified_models_and_manifest(self) -> None:
        payload = b"small-verified-model"
        asset = ModelAsset(
            key="release-fixture",
            relative_path=Path("fixture") / "model.pth",
            url="https://example.invalid/model.pth",
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            source="https://example.invalid",
            revision="fixture",
            license="Apache-2.0",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = root / "prepared"
            (prepared / "frontend").mkdir(parents=True)
            (prepared / "run_vision2grasp_app.py").write_text("# fixture\n", encoding="utf-8")
            (prepared / "frontend" / "index.html").write_text("fixture", encoding="utf-8")
            cache = root / "cache"
            cached_model = cache / asset.relative_path
            cached_model.parent.mkdir(parents=True)
            cached_model.write_bytes(payload)
            output = root / "Vision2Grasp-windows-x64.zip"
            resolver = ModelAssetResolver(release_model_roots=(), user_cache=cache)
            with patch("scripts.build_release.REQUIRED_MODELS", (asset,)):
                build_release_zip(
                    prepared_app=prepared,
                    output_zip=output,
                    resolver=resolver,
                    allow_download=False,
                )
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("Vision2Grasp/models/fixture/model.pth", names)
                self.assertIn("Vision2Grasp/release-models.json", names)
                self.assertIn("Vision2Grasp/THIRD_PARTY_NOTICES.md", names)
                manifest = json.loads(
                    archive.read("Vision2Grasp/release-models.json").decode("utf-8")
                )
            self.assertEqual(manifest["models"][0]["verified_sha256"], asset.sha256)

    def test_release_manifest_documents_depth_project_compatibility_priority(self) -> None:
        from scripts.build_release import model_manifest
        from vision2grasp.spatial_perception import DEPTH_MODEL_ASSET

        document = model_manifest(())
        self.assertEqual(
            document["lookup_priority"][DEPTH_MODEL_ASSET.key],
            [
                "RELEASE_BUNDLE",
                "PROJECT_COMPATIBLE",
                "USER_CACHE",
                "NETWORK_DOWNLOAD",
            ],
        )


if __name__ == "__main__":
    unittest.main()
