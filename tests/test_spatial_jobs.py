from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest

import numpy as np

from vision2grasp import RGBFrame
from vision2grasp.spatial_perception import (
    CalibrationState,
    DepthFrame,
    DepthMode,
    DepthSource,
    MaskSpatialPerceptionProvider,
    NominalFOVCameraIntrinsicsProvider,
    PersistentDepthWorkerProvider,
    SpatialPerceptionService,
    SpatialStage,
    SpatialTimingHistory,
    SpatialWatchdogConfig,
    SpatialWorkerTimeoutError,
    TimingProfile,
)
from vision2grasp.target_perception import TargetInstance, TargetSceneSnapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPTH_CACHE = (
    Path.home()
    / "AppData"
    / "Local"
    / "Vision2Grasp"
    / "model-cache"
    / "depth-anything-v2-metric-indoor-small"
    / "depth_anything_v2_metric_hypersim_vits.pth"
)


def make_snapshot(frame_id: int = 1) -> TargetSceneSnapshot:
    rgb = np.full((48, 64, 3), 120, dtype=np.uint8)
    mask = np.zeros((48, 64), dtype=np.bool_)
    mask[12:36, 18:50] = True
    frame = RGBFrame(frame_id, float(frame_id) + 0.25, "phone-live", rgb)
    return TargetSceneSnapshot(
        snapshot_id=f"snapshot-job-{frame_id}",
        frame=frame,
        target=TargetInstance(
            instance_id=f"target-job-{frame_id}",
            mask=mask,
            bbox_xyxy=(18.0, 12.0, 50.0, 36.0),
            centroid_2d=(33.5, 23.5),
            source_frame_id=frame.frame_id,
            source_timestamp_s=frame.timestamp_s,
        ),
    )


class _ConstantDepthProvider:
    model_ready = True

    def infer(self, frame: RGBFrame, progress=None) -> DepthFrame:
        if progress is not None:
            progress(
                SpatialStage.DEPTH_INFERENCE,
                {"model_state": "READY", "model_was_ready": True},
            )
        return DepthFrame(
            source_frame_id=frame.frame_id,
            source_timestamp_s=frame.timestamp_s,
            values=np.full(frame.rgb.shape[:2], 1.2, dtype=np.float32),
            source=DepthSource.MONOCULAR,
            native_mode=DepthMode.METRIC,
            inference_time_s=0.01,
            model_was_ready=True,
        )


class _BlockingDepthProvider(_ConstantDepthProvider):
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def infer(self, frame: RGBFrame, progress=None) -> DepthFrame:
        if progress is not None:
            progress(SpatialStage.DEPTH_INFERENCE, {"model_state": "READY"})
        self.entered.set()
        self.release.wait(timeout=4.0)
        return super().infer(frame, progress)


class _SupersedableProvider:
    model_ready = True

    def __init__(self) -> None:
        self._provider = MaskSpatialPerceptionProvider(
            _ConstantDepthProvider(), NominalFOVCameraIntrinsicsProvider()
        )
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def analyze(self, snapshot, progress=None):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            self.release.wait(timeout=4.0)
        return self._provider.analyze(snapshot, progress)

    def cancel_current(self) -> None:
        self.release.set()


class _SlowPointCloudProvider:
    model_ready = True

    def __init__(self) -> None:
        self._provider = MaskSpatialPerceptionProvider(
            _ConstantDepthProvider(), NominalFOVCameraIntrinsicsProvider()
        )
        self.entered = threading.Event()
        self.release = threading.Event()

    def analyze(self, snapshot, progress=None):
        def report(stage, details=None):
            if progress is not None:
                progress(stage, details)
            if stage is SpatialStage.POINT_CLOUD_BUILDING:
                self.entered.set()
                self.release.wait(timeout=2.0)

        return self._provider.analyze(snapshot, report)


def _hanging_model_worker(commands, events, _config) -> None:
    command = commands.get()
    if command.get("kind") == "STOP":
        return
    request_id = command["request_id"]
    events.put(
        {
            "kind": "PROGRESS",
            "request_id": request_id,
            "stage": "MODEL_LOADING",
            "details": {},
        }
    )
    time.sleep(10.0)


def _stalled_download_worker(commands, events, _config) -> None:
    command = commands.get()
    if command.get("kind") == "STOP":
        return
    request_id = command["request_id"]
    events.put(
        {
            "kind": "PROGRESS",
            "request_id": request_id,
            "stage": "MODEL_DOWNLOADING",
            "details": {"bytes_downloaded": 1024, "bytes_total": 4096},
        }
    )
    time.sleep(10.0)


def short_watchdog() -> SpatialWatchdogConfig:
    return SpatialWatchdogConfig(
        heartbeat_interval_s=0.02,
        download_warning_stall_s=0.05,
        download_timeout_stall_s=0.15,
        checksum_warning_s=0.05,
        checksum_timeout_s=0.15,
        model_loading_warning_s=0.05,
        model_loading_timeout_s=0.15,
        depth_inference_warning_s=0.05,
        depth_inference_timeout_s=0.15,
        point_cloud_warning_s=0.05,
        point_cloud_timeout_s=0.15,
        spatial_computing_warning_s=0.05,
        spatial_computing_timeout_s=0.15,
    )


class SpatialJobTests(unittest.TestCase):
    def test_start_returns_immediately_and_state_heartbeat_keeps_advancing(self) -> None:
        depth = _BlockingDepthProvider()
        service = SpatialPerceptionService(
            MaskSpatialPerceptionProvider(
                depth, NominalFOVCameraIntrinsicsProvider()
            )
        )
        snapshot = make_snapshot(11)
        started = time.perf_counter()
        initial = service.start(
            snapshot,
            expected_snapshot_id=snapshot.snapshot_id,
            expected_source_frame_id=snapshot.frame.frame_id,
            expected_target_instance_id=snapshot.target.instance_id,
            expected_source_timestamp_s=snapshot.frame.timestamp_s,
        )
        self.assertLess(time.perf_counter() - started, 0.2)
        self.assertTrue(depth.entered.wait(timeout=1.0))
        first = service.snapshot()
        time.sleep(0.55)
        second = service.snapshot()
        self.assertEqual(initial["binding"]["job_id"], initial["job_id"])
        self.assertEqual(second["binding"]["snapshot_id"], snapshot.snapshot_id)
        self.assertGreater(second["last_heartbeat_at"], first["last_heartbeat_at"])
        depth.release.set()
        ready = service.wait(str(initial["job_id"]), timeout_s=3.0)
        self.assertEqual(ready["status"], "READY")

    def test_retry_supersedes_old_job_and_discards_its_late_result(self) -> None:
        provider = _SupersedableProvider()
        service = SpatialPerceptionService(provider)
        first_snapshot = make_snapshot(21)
        first = service.start(
            first_snapshot,
            expected_snapshot_id=first_snapshot.snapshot_id,
            expected_source_frame_id=first_snapshot.frame.frame_id,
            expected_target_instance_id=first_snapshot.target.instance_id,
            expected_source_timestamp_s=first_snapshot.frame.timestamp_s,
        )
        self.assertTrue(provider.entered.wait(timeout=1.0))
        second_snapshot = make_snapshot(22)
        second = service.start(
            second_snapshot,
            expected_snapshot_id=second_snapshot.snapshot_id,
            expected_source_frame_id=second_snapshot.frame.frame_id,
            expected_target_instance_id=second_snapshot.target.instance_id,
            expected_source_timestamp_s=second_snapshot.frame.timestamp_s,
        )
        ready = service.wait(str(second["job_id"]), timeout_s=3.0)
        self.assertEqual(ready["status"], "READY")
        self.assertEqual(ready["observation"]["source_frame_id"], 22)
        self.assertNotEqual(first["job_id"], second["job_id"])
        cancelled = {item["job_id"]: item for item in ready["cancelled_jobs"]}
        self.assertEqual(cancelled[first["job_id"]]["reason"], "SUPERSEDED")

    def test_scene_frame_target_and_job_binding_is_strict(self) -> None:
        service = SpatialPerceptionService(
            MaskSpatialPerceptionProvider(
                _ConstantDepthProvider(), NominalFOVCameraIntrinsicsProvider()
            )
        )
        snapshot = make_snapshot(31)
        with self.assertRaisesRegex(ValueError, "frame mismatch"):
            service.start(
                snapshot,
                expected_snapshot_id=snapshot.snapshot_id,
                expected_source_frame_id=999,
                expected_target_instance_id=snapshot.target.instance_id,
                expected_source_timestamp_s=snapshot.frame.timestamp_s,
            )

    def test_point_cloud_timeout_stays_failed_after_late_result_returns(self) -> None:
        provider = _SlowPointCloudProvider()
        service = SpatialPerceptionService(provider, watchdog=short_watchdog())
        snapshot = make_snapshot(32)
        initial = service.start(
            snapshot,
            expected_snapshot_id=snapshot.snapshot_id,
            expected_source_frame_id=snapshot.frame.frame_id,
            expected_target_instance_id=snapshot.target.instance_id,
            expected_source_timestamp_s=snapshot.frame.timestamp_s,
        )
        self.assertTrue(provider.entered.wait(timeout=1.0))
        failed = service.wait(str(initial["job_id"]), timeout_s=1.0)
        self.assertEqual(failed["status"], "FAILED")
        self.assertEqual(failed["error_code"], "POINT_CLOUD_TIMEOUT")
        provider.release.set()
        time.sleep(0.2)
        late = service.snapshot()
        self.assertEqual(late["status"], "FAILED")
        self.assertEqual(late["error_code"], "POINT_CLOUD_TIMEOUT")


class PersistentDepthWorkerTests(unittest.TestCase):
    def test_cancelled_request_releases_lock_and_rebuilds_worker(self) -> None:
        provider = PersistentDepthWorkerProvider(
            watchdog=short_watchdog(), worker_target=_hanging_model_worker
        )
        entered = threading.Event()
        errors: list[BaseException] = []

        def run() -> None:
            try:
                provider.infer(
                    make_snapshot(40).frame,
                    lambda stage, _details=None: (
                        entered.set() if stage is SpatialStage.MODEL_LOADING else None
                    ),
                )
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(entered.wait(timeout=2.0))
            previous_pid = provider.worker_pid
            provider.cancel_current()
            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())
            self.assertTrue(errors)
            self.assertEqual(
                getattr(errors[0], "code", None), "SPATIAL_JOB_CANCELLED"
            )
            self.assertNotEqual(provider.worker_pid, previous_pid)
        finally:
            provider.close()

    def test_model_loading_timeout_terminates_and_rebuilds_worker(self) -> None:
        provider = PersistentDepthWorkerProvider(
            watchdog=short_watchdog(), worker_target=_hanging_model_worker
        )
        frame = make_snapshot(41).frame
        try:
            with self.assertRaises(SpatialWorkerTimeoutError) as raised:
                provider.infer(frame)
            self.assertEqual(raised.exception.code, "MODEL_LOAD_TIMEOUT")
            self.assertIsNotNone(provider.worker_pid)
            self.assertFalse(provider.model_ready)
        finally:
            provider.close()

    def test_download_stall_triggers_download_timeout(self) -> None:
        provider = PersistentDepthWorkerProvider(
            watchdog=short_watchdog(), worker_target=_stalled_download_worker
        )
        try:
            with self.assertRaises(SpatialWorkerTimeoutError) as raised:
                provider.infer(make_snapshot(42).frame)
            self.assertEqual(raised.exception.code, "DOWNLOAD_TIMEOUT")
        finally:
            provider.close()

    @unittest.skipUnless(DEPTH_CACHE.is_file(), "verified Depth checkpoint missing")
    def test_real_worker_uses_cache_then_reuses_persistent_warm_model(self) -> None:
        provider = PersistentDepthWorkerProvider()
        progress_events: list[tuple[str, dict[str, object]]] = []
        frame = make_snapshot(51).frame
        try:
            cold = provider.infer(
                frame,
                lambda stage, details=None: progress_events.append(
                    (stage.value, dict(details or {}))
                ),
            )
            cold_worker_pid = provider.worker_pid
            warm = provider.infer(frame)
            warm_worker_pid = provider.worker_pid
        finally:
            provider.close()
        stages = [stage for stage, _details in progress_events]
        self.assertNotIn("MODEL_DOWNLOADING", stages)
        self.assertIn("CHECKSUM_VERIFYING", stages)
        self.assertFalse(cold.model_was_ready)
        self.assertTrue(warm.model_was_ready)
        self.assertEqual(cold.model_location, "USER_CACHE")
        self.assertEqual(cold_worker_pid, warm_worker_pid)
        diagnostics = [
            details["resolver_diagnostic"]
            for _stage, details in progress_events
            if isinstance(details.get("resolver_diagnostic"), dict)
        ]
        selected = [item for item in diagnostics if item.get("accepted")]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["candidate_path"], str(DEPTH_CACHE))
        self.assertEqual(selected[0]["selected_source"], "USER_CACHE")
        self.assertEqual(selected[0]["checksum_result"], "MATCH")


class SpatialTimingHistoryTests(unittest.TestCase):
    def test_benchmark_seeds_real_cold_and_warm_eta_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            history = SpatialTimingHistory(
                Path(temporary) / "timings.json",
                benchmark_path=(
                    PROJECT_ROOT / "artifacts" / "benchmarks" / "spatial-v0.5-cpu.json"
                ),
            )
            cold = history.estimate(
                TimingProfile(
                    "depth-anything-v2-metric-indoor-small", "cpu", 518, True
                ),
                stage="MODEL_LOADING",
                stage_elapsed_s=1.0,
                total_elapsed_s=1.0,
            )
            warm = history.estimate(
                TimingProfile(
                    "depth-anything-v2-metric-indoor-small", "cpu", 518, False
                ),
                stage="DEPTH_INFERENCE",
                stage_elapsed_s=0.1,
                total_elapsed_s=0.1,
            )
        self.assertTrue(cold["available"])
        self.assertAlmostEqual(float(cold["stage_median_s"]), 3.1353098, places=3)
        self.assertEqual(warm["stage_sample_count"], 3)
        self.assertGreater(float(warm["estimated_remaining_s"]), 0.0)


if __name__ == "__main__":
    unittest.main()
