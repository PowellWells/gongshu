from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time
import tomllib
import unittest
from urllib.request import Request, urlopen

import numpy as np

from run_vision2grasp_app import AppRequestHandler
from vision2grasp.contracts import RGBFrame
from vision2grasp.contracts import CameraIntrinsics
from vision2grasp.model_assets import (
    ModelAssetResolver,
    default_user_model_cache,
    verify_model_file,
)
from vision2grasp.spatial_perception import (
    CalibratedCameraIntrinsicsProvider,
    CalibrationState,
    DEPTH_MODEL_ASSET,
    DepthFrame,
    DepthCalibrationMode,
    DepthMode,
    DepthSource,
    DepthUnavailableError,
    GeometrySanityStatus,
    INTRINSICS_SOURCE_PRIORITY,
    IntrinsicsSource,
    IntrinsicsObservation,
    MaskSpatialPerceptionConfig,
    MaskSpatialPerceptionProvider,
    MonocularDepthConfig,
    MonocularDepthProvider,
    MODEL_FILES,
    MODEL_LICENSE,
    MODEL_REVISION,
    MODEL_SHA256,
    NominalFOVCameraIntrinsicsProvider,
    PriorityCameraIntrinsicsProvider,
    SpatialPerceptionService,
    SpatialStage,
)
from vision2grasp.target_perception import TargetInstance, TargetSceneSnapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_snapshot(*, frame_id: int = 41, timestamp_s: float = 8.25) -> TargetSceneSnapshot:
    rgb = np.zeros((48, 64, 3), dtype=np.uint8)
    rgb[..., 0] = np.arange(64, dtype=np.uint8)[None, :]
    mask = np.zeros((48, 64), dtype=np.bool_)
    mask[12:36, 18:50] = True
    frame = RGBFrame(frame_id, timestamp_s, "phone-frozen", rgb)
    target = TargetInstance(
        instance_id=f"target-{frame_id}-01",
        mask=mask,
        bbox_xyxy=(18.0, 12.0, 50.0, 36.0),
        centroid_2d=(33.5, 23.5),
        source_frame_id=frame_id,
        source_timestamp_s=timestamp_s,
    )
    return TargetSceneSnapshot(
        snapshot_id=f"snapshot-{frame_id}-fixture",
        frame=frame,
        target=target,
    )


class _DepthProvider:
    def __init__(self, values: np.ndarray, mode: DepthMode = DepthMode.METRIC) -> None:
        self.values = np.asarray(values, dtype=np.float32)
        self.mode = mode
        self.frames: list[int] = []

    def infer(self, frame: RGBFrame, progress=None) -> DepthFrame:
        self.frames.append(frame.frame_id)
        return DepthFrame(
            source_frame_id=frame.frame_id,
            source_timestamp_s=frame.timestamp_s,
            values=self.values,
            source=DepthSource.MONOCULAR,
            native_mode=self.mode,
            inference_time_s=0.125,
        )


class _UnavailableDepthProvider:
    def infer(self, frame: RGBFrame, progress=None) -> DepthFrame:
        raise DepthUnavailableError("depth weights unavailable")


class _InvalidIntrinsicsProvider:
    def resolve(self, frame: RGBFrame) -> IntrinsicsObservation:
        return IntrinsicsObservation(
            intrinsics=CameraIntrinsics(
                width=frame.rgb.shape[1],
                height=frame.rgb.shape[0],
                fx=float("nan"),
                fy=100.0,
                cx=10.0,
                cy=10.0,
            ),
            source=IntrinsicsSource.NOMINAL_FOV,
            calibration_state=CalibrationState.UNCALIBRATED,
            nominal_fov_deg=75.0,
        )


class SpatialPerceptionProviderTests(unittest.TestCase):
    def test_default_config_freezes_cpu_backend_fov_and_verified_model_metadata(self) -> None:
        with (PROJECT_ROOT / "configs" / "default.toml").open("rb") as stream:
            config = tomllib.load(stream)["spatial_perception"]
        self.assertEqual(config["device"], "cpu")
        self.assertEqual(config["backend"], "depth_anything_v2_metric_indoor_small")
        self.assertEqual(config["model_revision"], MODEL_REVISION)
        self.assertEqual(config["input_size"], 518)
        self.assertEqual(
            tuple(source.upper() for source in config["intrinsics_priority"]),
            tuple(source.value for source in INTRINSICS_SOURCE_PRIORITY),
        )
        self.assertEqual(config["nominal_diagonal_fov_deg"], 75.0)
        self.assertEqual(MODEL_LICENSE, "Apache-2.0")
        self.assertEqual(
            MODEL_FILES[DEPTH_MODEL_ASSET.relative_path.name][1],
            MODEL_SHA256,
        )
        project = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("transformers", project)

    def test_nominal_fov_intrinsics_are_uncalibrated_and_orientation_safe(self) -> None:
        snapshot = make_snapshot()
        observation = NominalFOVCameraIntrinsicsProvider().resolve(snapshot.frame)
        self.assertEqual(observation.source, IntrinsicsSource.NOMINAL_FOV)
        self.assertEqual(observation.calibration_state, CalibrationState.UNCALIBRATED)
        self.assertEqual(observation.depth_calibration_mode, DepthCalibrationMode.NONE)
        self.assertEqual(observation.intrinsics.width, 64)
        self.assertEqual(observation.intrinsics.height, 48)
        self.assertAlmostEqual(observation.intrinsics.fx, observation.intrinsics.fy)
        self.assertEqual(observation.nominal_fov_deg, 75.0)

    def test_device_agnostic_intrinsics_priority_uses_calibration_then_nominal_fov(self) -> None:
        snapshot = make_snapshot()
        calibrated = CameraIntrinsics(64, 48, 60.0, 61.0, 31.5, 23.5)
        resolver = PriorityCameraIntrinsicsProvider(
            (
                CalibratedCameraIntrinsicsProvider({"phone-frozen": calibrated}),
                NominalFOVCameraIntrinsicsProvider(),
            )
        )
        observation = resolver.resolve(snapshot.frame)
        self.assertEqual(observation.source, IntrinsicsSource.CALIBRATED)
        self.assertEqual(observation.calibration_state, CalibrationState.CALIBRATED)

        fallback = PriorityCameraIntrinsicsProvider(
            (
                CalibratedCameraIntrinsicsProvider(),
                NominalFOVCameraIntrinsicsProvider(),
            )
        ).resolve(snapshot.frame)
        self.assertEqual(fallback.source, IntrinsicsSource.NOMINAL_FOV)
        self.assertEqual(fallback.calibration_state, CalibrationState.UNCALIBRATED)
        with self.assertRaisesRegex(ValueError, "priority order"):
            PriorityCameraIntrinsicsProvider(
                (
                    NominalFOVCameraIntrinsicsProvider(),
                    CalibratedCameraIntrinsicsProvider(),
                )
            )

    def test_calibrated_intrinsics_can_be_loaded_without_phone_model_hardcoding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "camera-intrinsics.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "vision2grasp.camera-intrinsics/v1",
                        "cameras": {
                            "phone-frozen": {
                                "width": 64,
                                "height": 48,
                                "fx": 60.0,
                                "fy": 61.0,
                                "cx": 31.5,
                                "cy": 23.5,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            observation = CalibratedCameraIntrinsicsProvider.from_user_config(path).resolve_candidate(
                make_snapshot().frame
            )
        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(observation.source, IntrinsicsSource.CALIBRATED)

    def test_metric_scaled_monocular_depth_with_nominal_intrinsics_is_only_approx_metric(self) -> None:
        snapshot = make_snapshot()
        depth = np.full((48, 64), 1.50, dtype=np.float32)
        depth[12, 18] = np.nan
        depth[13, 19] = 9.0
        provider = _DepthProvider(depth, DepthMode.METRIC)
        analyzer = MaskSpatialPerceptionProvider(
            provider,
            NominalFOVCameraIntrinsicsProvider(),
            MaskSpatialPerceptionConfig(maximum_points=100),
        )
        result = analyzer.analyze(snapshot)
        self.assertEqual(provider.frames, [snapshot.frame.frame_id])
        self.assertEqual(result.snapshot_id, snapshot.snapshot_id)
        self.assertEqual(result.target_instance_id, snapshot.target.instance_id)
        self.assertEqual(result.depth_mode, DepthMode.APPROX_METRIC)
        self.assertEqual(result.unit, "m")
        self.assertAlmostEqual(result.target_depth.value, 1.50, places=5)
        self.assertLess(result.target_depth.valid_ratio, 1.0)
        self.assertLess(result.target_depth.inlier_ratio, 1.0)
        self.assertEqual(result.target_point_cloud.shape, (100, 3))
        self.assertAlmostEqual(result.centroid_xyz[2], 1.50, places=5)
        metadata = result.public_metadata()
        self.assertEqual(metadata["camera_frame"], "OPENCV_CAMERA_X_RIGHT_Y_DOWN_Z_FORWARD")
        self.assertEqual(metadata["calibration_state"], "UNCALIBRATED")
        self.assertEqual(metadata["intrinsics_source"], "NOMINAL_FOV")
        self.assertEqual(metadata["scale_mode"], "DIRECT")
        self.assertEqual(metadata["geometry_chain_id"], snapshot.geometry_chain_id)
        self.assertEqual(metadata["geometry_sanity"]["status"], GeometrySanityStatus.PASS.value)
        diagnostics = metadata["geometry_diagnostics"]
        self.assertEqual(diagnostics["snapshot_size"], {"width": 64, "height": 48})
        self.assertEqual(diagnostics["depth_size"], {"width": 64, "height": 48})
        self.assertEqual(diagnostics["mask_size"], {"width": 64, "height": 48})
        self.assertTrue(diagnostics["geometry_aligned"])
        self.assertFalse(diagnostics["crop_applied"])
        self.assertFalse(diagnostics["rotation_applied"])
        self.assertFalse(diagnostics["letterbox_applied"])
        self.assertEqual(diagnostics["display_object_fit"], "contain")
        self.assertEqual(diagnostics["intrinsics_source"], "NOMINAL_FOV")
        self.assertEqual(diagnostics["calibration_state"], "UNCALIBRATED")
        self.assertEqual(diagnostics["depth_mode"], "APPROX_METRIC")
        self.assertEqual(diagnostics["geometry_chain_id"], snapshot.geometry_chain_id)
        self.assertAlmostEqual(diagnostics["fx"], result.camera_intrinsics.intrinsics.fx)
        self.assertAlmostEqual(diagnostics["valid_depth_ratio"], result.target_depth.valid_ratio)
        np.testing.assert_allclose(diagnostics["target_centroid_xyz"], result.centroid_xyz)
        self.assertEqual(diagnostics["target_bbox_pixels"]["width"], 32.0)
        self.assertAlmostEqual(diagnostics["target_depth_median"], 1.5)
        self.assertEqual(len(diagnostics["point_cloud_extent_xyz"]), 3)

    def test_portrait_270x480_and_540x960_share_one_geometry_coordinate_system(self) -> None:
        def analyze(width: int, height: int):
            rgb = np.zeros((height, width, 3), dtype=np.uint8)
            mask = np.zeros((height, width), dtype=np.bool_)
            x1, x2 = width // 4, 3 * width // 4
            y1, y2 = height // 4, 3 * height // 4
            mask[y1:y2, x1:x2] = True
            frame = RGBFrame(width, 10.0 + width, "phone-portrait", rgb)
            snapshot = TargetSceneSnapshot(
                snapshot_id=f"snapshot-{width}x{height}",
                frame=frame,
                target=TargetInstance(
                    instance_id=f"target-{width}x{height}",
                    mask=mask,
                    bbox_xyxy=(float(x1), float(y1), float(x2), float(y2)),
                    centroid_2d=((x1 + x2 - 1) / 2.0, (y1 + y2 - 1) / 2.0),
                    source_frame_id=frame.frame_id,
                    source_timestamp_s=frame.timestamp_s,
                ),
            )
            return MaskSpatialPerceptionProvider(
                _DepthProvider(np.full((height, width), 0.30, dtype=np.float32)),
                NominalFOVCameraIntrinsicsProvider(),
            ).analyze(snapshot)

        low = analyze(270, 480)
        high = analyze(540, 960)
        low_diag = low.geometry_diagnostics
        high_diag = high.geometry_diagnostics
        self.assertIsNotNone(low_diag)
        self.assertIsNotNone(high_diag)
        assert low_diag is not None and high_diag is not None
        self.assertEqual(low_diag.snapshot_size, low_diag.depth_size)
        self.assertEqual(low_diag.snapshot_size, low_diag.mask_size)
        self.assertEqual(high_diag.snapshot_size, high_diag.depth_size)
        self.assertEqual(high_diag.snapshot_size, high_diag.mask_size)
        self.assertTrue(low_diag.geometry_aligned)
        self.assertTrue(high_diag.geometry_aligned)
        self.assertAlmostEqual(low_diag.nominal_hfov_deg, high_diag.nominal_hfov_deg, places=10)
        self.assertAlmostEqual(low_diag.nominal_vfov_deg, high_diag.nominal_vfov_deg, places=10)
        np.testing.assert_allclose(
            low_diag.point_cloud_extent_xyz,
            high_diag.point_cloud_extent_xyz,
            rtol=0.01,
            atol=5e-4,
        )
        np.testing.assert_allclose(low.centroid_xyz, high.centroid_xyz, atol=5e-4)

    def test_relative_backend_stays_relative_despite_nominal_intrinsics(self) -> None:
        snapshot = make_snapshot()
        depth = np.full((48, 64), 0.65, dtype=np.float32)
        result = MaskSpatialPerceptionProvider(
            _DepthProvider(depth, DepthMode.RELATIVE),
            NominalFOVCameraIntrinsicsProvider(),
        ).analyze(snapshot)
        self.assertEqual(result.depth_mode, DepthMode.RELATIVE)
        self.assertEqual(result.unit, "relative")
        self.assertEqual(result.public_metadata()["unit"], "relative")

    def test_rejects_too_few_valid_depth_pixels_without_point_cloud(self) -> None:
        snapshot = make_snapshot()
        depth = np.full((48, 64), np.nan, dtype=np.float32)
        depth[20:22, 20:22] = 1.0
        with self.assertRaisesRegex(ValueError, "below minimum"):
            MaskSpatialPerceptionProvider(
                _DepthProvider(depth),
                NominalFOVCameraIntrinsicsProvider(),
            ).analyze(snapshot)

    def test_rejects_invalid_intrinsics_before_backprojection(self) -> None:
        snapshot = make_snapshot()
        with self.assertRaisesRegex(ValueError, "intrinsics"):
            MaskSpatialPerceptionProvider(
                _DepthProvider(np.full((48, 64), 1.0, dtype=np.float32)),
                _InvalidIntrinsicsProvider(),
            ).analyze(snapshot)


class SpatialPerceptionServiceTests(unittest.TestCase):
    @staticmethod
    def _analyze(service: SpatialPerceptionService, snapshot: TargetSceneSnapshot, **overrides):
        values = {
            "expected_snapshot_id": snapshot.snapshot_id,
            "expected_source_frame_id": snapshot.frame.frame_id,
            "expected_target_instance_id": snapshot.target.instance_id,
            "expected_source_timestamp_s": snapshot.frame.timestamp_s,
        }
        values.update(overrides)
        return service.analyze(snapshot, **values)

    def test_strict_snapshot_association_and_depth_failure_produce_error_without_fake_output(self) -> None:
        snapshot = make_snapshot()
        service = SpatialPerceptionService(
            MaskSpatialPerceptionProvider(
                _UnavailableDepthProvider(),
                NominalFOVCameraIntrinsicsProvider(),
            )
        )
        mismatched = service.analyze(
            snapshot,
            expected_snapshot_id="wrong-snapshot",
            expected_source_frame_id=snapshot.frame.frame_id,
            expected_target_instance_id=snapshot.target.instance_id,
            expected_source_timestamp_s=snapshot.frame.timestamp_s,
        )
        self.assertEqual(mismatched["status"], "ERROR")
        self.assertEqual(mismatched["error_code"], "FRAME_MISMATCH")
        self.assertIsNone(mismatched["observation"])
        self.assertFalse(mismatched["media"]["overview_available"])

        unavailable = service.analyze(
            snapshot,
            expected_snapshot_id=snapshot.snapshot_id,
            expected_source_frame_id=snapshot.frame.frame_id,
            expected_target_instance_id=snapshot.target.instance_id,
            expected_source_timestamp_s=snapshot.frame.timestamp_s,
        )
        self.assertEqual(unavailable["status"], "ERROR")
        self.assertEqual(unavailable["error_code"], "DEPTH_UNAVAILABLE")
        self.assertIsNone(unavailable["observation"])
        self.assertIsNone(service.overview_jpeg())

    def test_error_taxonomy_covers_invalid_intrinsics_sparse_depth_target_and_empty_cloud(self) -> None:
        snapshot = make_snapshot()
        sparse = np.full((48, 64), np.nan, dtype=np.float32)
        sparse[20:22, 20:22] = 1.0
        sparse_service = SpatialPerceptionService(
            MaskSpatialPerceptionProvider(
                _DepthProvider(sparse),
                NominalFOVCameraIntrinsicsProvider(),
            )
        )
        self.assertEqual(self._analyze(sparse_service, snapshot)["error_code"], "TOO_FEW_VALID_DEPTH_PIXELS")

        intrinsics_service = SpatialPerceptionService(
            MaskSpatialPerceptionProvider(
                _DepthProvider(np.full((48, 64), 1.0, dtype=np.float32)),
                _InvalidIntrinsicsProvider(),
            )
        )
        self.assertEqual(self._analyze(intrinsics_service, snapshot)["error_code"], "INVALID_INTRINSICS")

        target_service = SpatialPerceptionService(
            MaskSpatialPerceptionProvider(
                _DepthProvider(np.full((48, 64), 1.0, dtype=np.float32)),
                NominalFOVCameraIntrinsicsProvider(),
            )
        )
        target_error = self._analyze(
            target_service,
            snapshot,
            expected_target_instance_id="wrong-target",
        )
        self.assertEqual(target_error["error_code"], "TARGET_MISMATCH")
        self.assertIsNone(target_error["observation"])
        self.assertEqual(
            SpatialPerceptionService._classify_error(ValueError("target mask is empty")),
            "TARGET_MASK_EMPTY",
        )
        self.assertEqual(
            SpatialPerceptionService._classify_error(ValueError("target point cloud is empty")),
            "POINT_CLOUD_EMPTY",
        )

    def test_ready_state_contains_real_overview_and_no_backend_model_name(self) -> None:
        snapshot = make_snapshot()
        service = SpatialPerceptionService(
            MaskSpatialPerceptionProvider(
                _DepthProvider(np.full((48, 64), 1.2, dtype=np.float32)),
                NominalFOVCameraIntrinsicsProvider(),
            )
        )
        ready = service.analyze(
            snapshot,
            expected_snapshot_id=snapshot.snapshot_id,
            expected_source_frame_id=snapshot.frame.frame_id,
            expected_target_instance_id=snapshot.target.instance_id,
            expected_source_timestamp_s=snapshot.frame.timestamp_s,
        )
        self.assertEqual(ready["status"], "READY")
        self.assertEqual(ready["stage"], "READY")
        self.assertGreaterEqual(ready["timing"]["total_s"], 0.0)
        self.assertTrue(ready["media"]["overview_available"])
        self.assertGreater(len(service.overview_jpeg() or b""), 1000)
        self.assertNotIn("depth-anything", json.dumps(ready).lower())

    def test_backend_stage_and_elapsed_time_are_visible_while_request_is_running(self) -> None:
        snapshot = make_snapshot()
        entered = threading.Event()
        release = threading.Event()

        class _StagedDepthProvider(_DepthProvider):
            def infer(self, frame: RGBFrame, progress=None) -> DepthFrame:
                if progress is not None:
                    progress(SpatialStage.MODEL_LOADING, None)
                entered.set()
                release.wait(timeout=3)
                return super().infer(frame, progress)

        service = SpatialPerceptionService(
            MaskSpatialPerceptionProvider(
                _StagedDepthProvider(np.full((48, 64), 1.2, dtype=np.float32)),
                NominalFOVCameraIntrinsicsProvider(),
            )
        )
        result: dict[str, object] = {}

        def run() -> None:
            result.update(self._analyze(service, snapshot))

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(entered.wait(timeout=2))
        time.sleep(0.02)
        running = service.snapshot()
        self.assertEqual(running["status"], "ANALYZING")
        self.assertEqual(running["stage"], "MODEL_LOADING")
        self.assertGreater(running["timing"]["elapsed_s"], 0.0)
        release.set()
        thread.join(timeout=3)
        self.assertEqual(result["status"], "READY")


class MonocularDepthAdapterTests(unittest.TestCase):
    def test_infer_uses_official_resize_and_postprocesses_to_snapshot_size(self) -> None:
        import torch

        class _Model:
            def __call__(self, tensor):
                self.input_shape = tuple(tensor.shape)
                return torch.full((1, 4, 4), 0.42)

        provider = MonocularDepthProvider()
        model = _Model()
        provider._model = model
        provider._torch = torch
        frame = make_snapshot().frame
        result = provider.infer(frame)
        self.assertEqual(model.input_shape, (1, 3, 518, 686))
        self.assertEqual(result.model_input_size, (686, 518))
        self.assertEqual(result.values.shape, frame.rgb.shape[:2])
        np.testing.assert_allclose(result.values, 0.42, atol=1e-6)

    def test_missing_verified_pth_fails_before_model_load_when_download_disabled(self) -> None:
        directory = PROJECT_ROOT / "tmp" / "missing-depth-model"
        provider = MonocularDepthProvider(
            MonocularDepthConfig(allow_download=False),
            asset_resolver=ModelAssetResolver(
                release_model_roots=(),
                user_cache=directory,
            ),
        )
        with self.assertRaisesRegex(DepthUnavailableError, "unavailable"):
            provider.infer(make_snapshot().frame)


@unittest.skipUnless(
    verify_model_file(
        default_user_model_cache() / DEPTH_MODEL_ASSET.relative_path,
        DEPTH_MODEL_ASSET,
    ),
    "verified metric monocular depth checkpoint is not installed",
)
class MonocularDepthIntegrationTests(unittest.TestCase):
    def test_official_cpu_checkpoint_generates_approx_metric_spatial_observation(self) -> None:
        import cv2

        bgr = cv2.imread(str(PROJECT_ROOT / "artifacts" / "perception" / "bottle_cc0.jpg"))
        self.assertIsNotNone(bgr)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        frame = RGBFrame(991, 44.5, "static-depth-integration", rgb)
        height, width = rgb.shape[:2]
        mask = np.zeros((height, width), dtype=np.bool_)
        mask[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4] = True
        snapshot = TargetSceneSnapshot(
            snapshot_id="snapshot-991-depth-integration",
            frame=frame,
            target=TargetInstance(
                instance_id="target-991-manual-fixture",
                mask=mask,
                bbox_xyxy=(width / 4, height / 4, 3 * width / 4, 3 * height / 4),
                centroid_2d=(width / 2, height / 2),
                source_frame_id=frame.frame_id,
                source_timestamp_s=frame.timestamp_s,
            ),
        )
        result = MaskSpatialPerceptionProvider(
            MonocularDepthProvider(),
            NominalFOVCameraIntrinsicsProvider(),
        ).analyze(snapshot)
        self.assertEqual(result.depth_mode, DepthMode.APPROX_METRIC)
        self.assertEqual(result.depth_frame.native_mode, DepthMode.METRIC)
        self.assertEqual(result.depth_frame.values.shape, rgb.shape[:2])
        self.assertGreater(result.target_depth.value, 0.0)
        self.assertGreaterEqual(result.target_point_cloud.shape[0], 30)
        self.assertTrue(np.all(np.isfinite(result.centroid_xyz)))
        self.assertGreater(result.inference_time_s, 0.0)


class SpatialPerceptionHTTPTests(unittest.TestCase):
    def test_analyze_endpoint_uses_locked_snapshot_and_serves_real_overview(self) -> None:
        snapshot = make_snapshot(frame_id=87, timestamp_s=12.75)
        service = SpatialPerceptionService(
            MaskSpatialPerceptionProvider(
                _DepthProvider(np.full((48, 64), 1.35, dtype=np.float32)),
                NominalFOVCameraIntrinsicsProvider(),
            )
        )

        class _TargetPerception:
            def selected_scene_snapshot(self) -> TargetSceneSnapshot:
                return snapshot

        class _App:
            target_perception = _TargetPerception()
            spatial_perception = service

            def analyze_spatial(self, body: dict[str, object]) -> dict[str, object]:
                return self.spatial_perception.analyze(
                    snapshot,
                    expected_snapshot_id=str(body["snapshot_id"]),
                    expected_source_frame_id=int(body["source_frame_id"]),
                    expected_target_instance_id=str(body["target_instance_id"]),
                    expected_source_timestamp_s=float(body["source_timestamp_s"]),
                )

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(AppRequestHandler, app=_App()),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        body = snapshot.public_metadata()
        body["target_instance_id"] = body.pop("target_id")
        request = Request(
            f"{base_url}/api/spatial-perception/analyze",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=3) as response:
                ready = json.loads(response.read().decode("utf-8"))
            self.assertEqual(ready["status"], "READY")
            with urlopen(f"{base_url}/api/spatial-perception/overview.jpg", timeout=3) as response:
                self.assertEqual(response.headers.get_content_type(), "image/jpeg")
                self.assertGreater(len(response.read()), 1000)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
