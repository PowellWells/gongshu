from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import cv2
import numpy as np

from run_vision2grasp_app import Vision2GraspApp
from vision2grasp.contracts import RGBFrame
from vision2grasp.experiment_lab import ExperimentTrialRecorder
from vision2grasp.intelligence import IntelligenceService
from vision2grasp.sources import LocalImageAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GONGSHU_ROOT = PROJECT_ROOT / "frontend" / "apps" / "gongshu"


def image_bytes() -> bytes:
    bgr = np.zeros((12, 18, 3), dtype=np.uint8)
    bgr[:, :] = [10, 20, 30]
    ok, encoded = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("test image encoding failed")
    return encoded.tobytes()


class _Resettable:
    def __init__(self) -> None:
        self.reset_count = 0

    def reset(self) -> dict[str, str]:
        self.reset_count += 1
        return {"status": "WAITING"}


class _ConditionProcessor:
    @staticmethod
    def process(frame: RGBFrame, *_args, **_kwargs) -> RGBFrame:
        return frame


class _TargetPerception(_Resettable):
    def __init__(self) -> None:
        super().__init__()
        self.frames: list[RGBFrame] = []

    def analyze(self, frame: RGBFrame) -> dict[str, object]:
        self.frames.append(frame)
        return {
            "schema_version": "gongshu.target-perception/v1",
            "status": "CANDIDATES",
            "candidates": [],
            "frame": {"id": frame.frame_id, "width": frame.rgb.shape[1], "height": frame.rgb.shape[0]},
        }


class LocalImageAdapterTests(unittest.TestCase):
    def test_image_reading_returns_independent_standard_rgb_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = LocalImageAdapter(Path(temporary) / "artifacts" / "offline_run")
            adapter.load("sample.png", image_bytes())
            first = adapter.capture()
            second = adapter.capture()
            self.assertIsInstance(first, RGBFrame)
            self.assertEqual((first.rgb.shape, first.camera_name), ((12, 18, 3), "local-image"))
            self.assertEqual((first.frame_id, second.frame_id), (0, 1))
            first.rgb[0, 0] = 0
            self.assertEqual(second.rgb[0, 0].tolist(), [30, 20, 10])

    def test_load_creates_ready_observation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            adapter = LocalImageAdapter(Path(temporary) / "artifacts" / "offline_run")
            observation = adapter.load("桌面瓶子.png", image_bytes())
            self.assertEqual(observation.source, "local_image")
            self.assertEqual(observation.status, "ready")
            self.assertEqual(observation.image_name, "桌面瓶子.png")
            self.assertEqual((observation.width, observation.height), (18, 12))
            self.assertEqual(len(observation.sha256), 64)
            self.assertGreater(len(adapter.preview_jpeg() or b""), 100)

    def test_pipeline_entry_uses_existing_target_perception_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = object.__new__(Vision2GraspApp)
            app.local_image = LocalImageAdapter(Path(temporary) / "artifacts" / "offline_run")
            app.experiment_recorder = ExperimentTrialRecorder(
                Path(temporary) / "artifacts" / "offline_run"
            )
            app.intelligence = IntelligenceService(xiezhi_enabled=False)
            app._vision_source = "phone_camera"
            app.condition_experiment = _ConditionProcessor()
            app.target_perception = _TargetPerception()
            app.spatial_perception = _Resettable()
            app.grasp_planning = _Resettable()
            app.mujoco_validation = _Resettable()
            result = app.load_local_image(
                {
                    "filename": "sample.png",
                    "data_base64": base64.b64encode(image_bytes()).decode("ascii"),
                    "condition": "NORMAL",
                    "mode": "RESEARCH",
                }
            )
            self.assertEqual(result["status"], "ready")
            self.assertEqual(result["target_perception"]["status"], "CANDIDATES")
            self.assertEqual(len(app.target_perception.frames), 1)
            self.assertEqual(app._vision_source, "local_image")
            self.assertEqual(app.vision_source_snapshot()["source"], "local_image")

    def test_result_record_is_unique_and_tracks_pipeline_and_mujoco(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            records_root = Path(temporary) / "artifacts" / "offline_run"
            adapter = LocalImageAdapter(records_root)
            first = adapter.load("sample.png", image_bytes())
            adapter.record_pipeline_status("COMPLETED", run_id=first.run_id)
            adapter.record_mujoco_result({"status": "SUCCESS"}, run_id=first.run_id)
            second = adapter.load("sample.png", image_bytes())
            self.assertNotEqual(first.run_id, second.run_id)
            record = json.loads((records_root / first.run_id / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(record["input_source"], "local_image")
            self.assertEqual(record["pipeline_status"], "COMPLETED")
            self.assertEqual(record["mujoco_result"]["status"], "SUCCESS")
            self.assertTrue((records_root / first.run_id / "input.png").is_file())
            self.assertTrue((records_root / second.run_id / "run.json").is_file())


class LocalImageFrontendTests(unittest.TestCase):
    def test_single_image_selection_and_load_controls_are_wired(self) -> None:
        html = (GONGSHU_ROOT / "index.html").read_text(encoding="utf-8")
        controller = (GONGSHU_ROOT / "real-scene.js").read_text(encoding="utf-8")
        self.assertIn('value="local_image"', html)
        self.assertIn('id="localImageFile" type="file"', html)
        self.assertNotIn("multiple", html.split('id="localImageFile"', 1)[1].split(">", 1)[0])
        self.assertIn('id="loadLocalImageButton"', html)
        self.assertIn('/api/vision-source/local-image/load', controller)
        self.assertIn('els.localImageFile.addEventListener("change"', controller)
        self.assertIn('els.loadLocalImageButton.addEventListener("click", loadLocalImage)', controller)


if __name__ == "__main__":
    unittest.main()
