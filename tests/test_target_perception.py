from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from urllib.request import Request, urlopen

import cv2
import numpy as np

from vision2grasp import RGBFrame
from vision2grasp.target_perception import (
    UNKNOWN_TARGET_LABEL,
    FastSAMTargetSegmenter,
    FastSAMTargetSegmenterConfig,
    TargetInstance,
    TargetPerceptionService,
)
from run_vision2grasp_app import AppRequestHandler


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_frame(frame_id: int = 17, timestamp_s: float = 4.25) -> RGBFrame:
    rgb = np.full((40, 60, 3), 90, dtype=np.uint8)
    rgb[8:30, 14:42] = np.array([180, 70, 35], dtype=np.uint8)
    return RGBFrame(frame_id, timestamp_s, "phone-live", rgb)


def make_instance(frame: RGBFrame, *, class_name: str | None = None) -> TargetInstance:
    mask = np.zeros(frame.rgb.shape[:2], dtype=np.bool_)
    mask[8:30, 14:42] = True
    return TargetInstance(
        instance_id=f"target-{frame.frame_id}-01",
        mask=mask,
        bbox_xyxy=(14.0, 8.0, 42.0, 30.0),
        centroid_2d=(27.5, 18.5),
        source_frame_id=frame.frame_id,
        source_timestamp_s=frame.timestamp_s,
        confidence=None,
        class_name=class_name,
        semantic_source=None,
    )


class _UnknownSegmenter:
    def predict(self, frame: RGBFrame) -> tuple[TargetInstance, ...]:
        return (make_instance(frame),)


class _EmptySegmenter:
    def predict(self, _frame: RGBFrame) -> tuple[TargetInstance, ...]:
        return ()


class TargetInstanceContractTests(unittest.TestCase):
    def test_missing_class_and_confidence_normalize_without_blocking_selection(self) -> None:
        instance = make_instance(make_frame(), class_name=None)
        self.assertEqual(instance.class_name, UNKNOWN_TARGET_LABEL)
        self.assertIsNone(instance.confidence)
        self.assertTrue(instance.selectable)
        metadata = instance.public_metadata(selected=False)
        self.assertEqual(metadata["class_name"], UNKNOWN_TARGET_LABEL)
        self.assertEqual(metadata["state"], "SELECTABLE")
        self.assertNotIn("mask", metadata)
        with self.assertRaises(ValueError):
            instance.mask[8, 14] = False

    def test_rejects_empty_masks_and_invalid_frame_association(self) -> None:
        frame = make_frame()
        empty = np.zeros(frame.rgb.shape[:2], dtype=np.bool_)
        with self.assertRaisesRegex(ValueError, "target pixel"):
            TargetInstance(
                "empty",
                empty,
                (1.0, 1.0, 2.0, 2.0),
                (1.0, 1.0),
                frame.frame_id,
                frame.timestamp_s,
            )
        with self.assertRaisesRegex(ValueError, "source_frame_id"):
            TargetInstance(
                "bad-frame",
                np.ones((2, 2), dtype=np.bool_),
                (0.0, 0.0, 2.0, 2.0),
                (0.5, 0.5),
                -1,
                frame.timestamp_s,
            )


class FastSAMAdapterTests(unittest.TestCase):
    def test_converts_and_deduplicates_masks_without_semantic_class_dependency(self) -> None:
        frame = make_frame()
        height, width = frame.rgb.shape[:2]
        first = np.zeros((height, width), dtype=np.float32)
        first[7:31, 13:43] = 1.0
        duplicate = first.copy()
        second = np.zeros((height, width), dtype=np.float32)
        second[5:18, 45:58] = 1.0
        result = SimpleNamespace(
            boxes=SimpleNamespace(conf=np.array([0.92, 0.88, 0.75], dtype=np.float32)),
            masks=SimpleNamespace(data=np.stack([first, duplicate, second])),
        )

        class _Model:
            def predict(self, source, **kwargs):
                self.source = source
                self.kwargs = kwargs
                return [result]

        model = _Model()
        segmenter = FastSAMTargetSegmenter(
            FastSAMTargetSegmenterConfig(
                minimum_area_ratio=0.01,
                maximum_area_ratio=0.9,
                maximum_candidates=5,
                weights_sha256=None,
            ),
            model=model,
        )
        instances = segmenter.predict(frame)
        self.assertEqual(len(instances), 2)
        self.assertEqual(instances[0].class_name, UNKNOWN_TARGET_LABEL)
        self.assertIsNone(instances[0].semantic_source)
        self.assertEqual(instances[0].source_frame_id, frame.frame_id)
        self.assertAlmostEqual(instances[0].confidence or 0.0, 0.92, places=5)
        self.assertEqual(model.source.shape, frame.rgb.shape)
        self.assertEqual(model.kwargs["device"], "cpu")

    def test_missing_or_tampered_weights_fail_before_model_load(self) -> None:
        missing = PROJECT_ROOT / "tmp" / "missing-fastsam.pt"
        segmenter = FastSAMTargetSegmenter(
            FastSAMTargetSegmenterConfig(weights_path=missing, weights_sha256=None)
        )
        with self.assertRaises(FileNotFoundError):
            segmenter.predict(make_frame())


class TargetPerceptionServiceTests(unittest.TestCase):
    def test_no_candidates_cannot_enter_target_locked_state(self) -> None:
        frame = make_frame()
        service = TargetPerceptionService(_EmptySegmenter())
        state = service.analyze(frame)
        self.assertEqual(state["status"], "NO_CANDIDATES")
        self.assertIsNone(state["selected_target_id"])
        self.assertIsNone(state["scene_snapshot"])
        with self.assertRaisesRegex(RuntimeError, "no target candidates"):
            service.select("anything", source_frame_id=frame.frame_id)

    def test_unknown_target_selection_locks_same_frozen_frame(self) -> None:
        frame = make_frame()
        service = TargetPerceptionService(_UnknownSegmenter())
        candidates = service.analyze(frame)
        self.assertEqual(candidates["status"], "CANDIDATES")
        target = candidates["candidates"][0]
        self.assertEqual(target["class_name"], UNKNOWN_TARGET_LABEL)
        self.assertTrue(target["selectable"])
        self.assertIsNone(service.scene_snapshot_jpeg())

        selected = service.select(str(target["id"]), source_frame_id=frame.frame_id)
        self.assertEqual(selected["status"], "TARGET_LOCKED")
        self.assertEqual(selected["selected_target"]["state"], "LOCKED")
        self.assertEqual(selected["scene_snapshot"]["source_frame_id"], frame.frame_id)
        self.assertEqual(selected["scene_snapshot"]["source_timestamp_s"], frame.timestamp_s)
        self.assertEqual(selected["scene_snapshot"]["target_id"], target["id"])
        self.assertNotIn("depth", selected)
        self.assertNotIn("grasp", selected)
        self.assertNotIn("simulation", selected)
        snapshot = service.scene_snapshot_jpeg()
        self.assertIsNotNone(snapshot)
        decoded = cv2.imdecode(np.frombuffer(snapshot, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape[:2], frame.rgb.shape[:2])

    def test_selection_rejects_frame_mismatch(self) -> None:
        frame = make_frame()
        service = TargetPerceptionService(_UnknownSegmenter())
        state = service.analyze(frame)
        with self.assertRaisesRegex(ValueError, "does not match"):
            service.select(state["candidates"][0]["id"], source_frame_id=frame.frame_id + 1)

    def test_mask_hit_test_selects_only_an_explicit_clicked_instance(self) -> None:
        frame = make_frame()
        service = TargetPerceptionService(_UnknownSegmenter())
        service.analyze(frame)
        selected = service.select_at(
            source_x=20.5,
            source_y=12.5,
            source_frame_id=frame.frame_id,
        )
        self.assertEqual(selected["selected_target_id"], f"target-{frame.frame_id}-01")
        with self.assertRaisesRegex(ValueError, "did not hit"):
            service.select_at(
                source_x=2.0,
                source_y=2.0,
                source_frame_id=frame.frame_id,
            )


class TargetPerceptionHTTPTests(unittest.TestCase):
    def test_analyze_select_snapshot_and_reset_endpoints_preserve_frame_identity(self) -> None:
        frame = make_frame(frame_id=73, timestamp_s=9.75)

        class _App:
            def __init__(self) -> None:
                self.target_perception = TargetPerceptionService(_UnknownSegmenter())

            def analyze_phone_targets(self) -> dict[str, object]:
                return self.target_perception.analyze(frame)

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(AppRequestHandler, app=_App()),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"

        def post(path: str, body: dict[str, object] | None = None) -> dict[str, object]:
            request = Request(
                f"{base_url}{path}",
                data=json.dumps(body or {}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            analyzed = post("/api/target-perception/analyze")
            target_id = str(analyzed["candidates"][0]["id"])
            self.assertEqual(analyzed["frame"]["id"], frame.frame_id)
            with urlopen(f"{base_url}/api/target-perception/overlay.jpg", timeout=3) as response:
                self.assertEqual(response.headers.get_content_type(), "image/jpeg")
                self.assertGreater(len(response.read()), 100)

            selected = post(
                "/api/target-perception/select-at",
                {"source_x": 20.5, "source_y": 12.5, "source_frame_id": frame.frame_id},
            )
            self.assertEqual(selected["status"], "TARGET_LOCKED")
            self.assertEqual(selected["scene_snapshot"]["target_id"], target_id)
            self.assertEqual(selected["scene_snapshot"]["source_timestamp_s"], frame.timestamp_s)
            with urlopen(f"{base_url}/api/target-perception/scene-snapshot.jpg", timeout=3) as response:
                self.assertEqual(response.headers.get_content_type(), "image/jpeg")
                self.assertGreater(len(response.read()), 100)

            reset = post("/api/target-perception/reset")
            self.assertEqual(reset["status"], "IDLE")
            self.assertIsNone(reset["frame"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


@unittest.skipUnless(
    (PROJECT_ROOT / "artifacts" / "models" / "FastSAM-s.pt").is_file(),
    "official FastSAM-s checkpoint is not installed",
)
class FastSAMIntegrationTests(unittest.TestCase):
    def test_official_checkpoint_generates_selectable_unknown_instances(self) -> None:
        bgr = cv2.imread(str(PROJECT_ROOT / "artifacts" / "perception" / "bottle_cc0.jpg"))
        self.assertIsNotNone(bgr)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        frame = RGBFrame(41, 8.0, "integration-image", rgb)
        instances = FastSAMTargetSegmenter().predict(frame)
        self.assertGreater(len(instances), 0)
        self.assertLessEqual(len(instances), 12)
        self.assertTrue(all(instance.selectable for instance in instances))
        self.assertTrue(all(instance.class_name == UNKNOWN_TARGET_LABEL for instance in instances))
        self.assertTrue(all(instance.source_frame_id == frame.frame_id for instance in instances))


if __name__ == "__main__":
    unittest.main()
