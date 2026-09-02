from __future__ import annotations

import time
import unittest
from dataclasses import replace
from functools import partial
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.request import Request, urlopen

import cv2
import numpy as np

from vision2grasp.contracts import CameraIntrinsics, RGBFrame
from vision2grasp.grasp_planning import (
    GRCONVNET_MODEL_ASSET,
    GRCONVNET_PROJECT_COMPATIBLE_PATHS,
    GRConvNetDetector,
    GraspMaps,
    GraspPlanningService,
    PixelWiseTopKGraspPlanner,
    PlanningMode,
    TopKGraspPlannerConfig,
)
from vision2grasp.model_assets import default_user_model_cache, verify_model_file
from vision2grasp.spatial_perception import (
    CalibrationState,
    DEPTH_MODEL_ASSET,
    DepthFrame,
    DepthMode,
    DepthSource,
    GeometrySanity,
    GeometrySanityStatus,
    IntrinsicsObservation,
    IntrinsicsSource,
    MaskSpatialPerceptionProvider,
    MonocularDepthProvider,
    NominalFOVCameraIntrinsicsProvider,
    SpatialObservation,
    TargetDepth,
)
from vision2grasp.target_perception import (
    FastSAMTargetSegmenter,
    FastSAMTargetSegmenterConfig,
    TargetInstance,
    TargetPerceptionService,
    TargetSceneSnapshot,
)
from run_vision2grasp_app import AppRequestHandler


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_snapshot() -> TargetSceneSnapshot:
    height = width = 100
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[10:90, 10:90] = (80, 140, 210)
    mask = np.zeros((height, width), dtype=np.bool_)
    mask[10:90, 10:90] = True
    frame = RGBFrame(71, 12.25, "test-frozen", rgb)
    target = TargetInstance(
        instance_id="target-71-01",
        mask=mask,
        bbox_xyxy=(10.0, 10.0, 90.0, 90.0),
        centroid_2d=(49.5, 49.5),
        source_frame_id=71,
        source_timestamp_s=12.25,
    )
    return TargetSceneSnapshot("snapshot-71", frame, target)


def make_observation(*, depth_value: float = 0.70) -> SpatialObservation:
    snapshot = make_snapshot()
    depth = np.full((100, 100), depth_value, dtype=np.float32)
    x = np.linspace(-0.035, 0.035, 35)
    y = np.linspace(-0.05, 0.05, 40)
    grid_x, grid_y = np.meshgrid(x, y)
    points = np.column_stack(
        (grid_x.ravel(), grid_y.ravel(), np.full(grid_x.size, depth_value))
    ).astype(np.float32)
    return SpatialObservation(
        snapshot_id=snapshot.snapshot_id,
        geometry_chain_id=snapshot.geometry_chain_id,
        source_frame_id=snapshot.frame.frame_id,
        target_instance_id=snapshot.target.instance_id,
        source_timestamp_s=snapshot.frame.timestamp_s,
        depth_frame=DepthFrame(
            source_frame_id=snapshot.frame.frame_id,
            source_timestamp_s=snapshot.frame.timestamp_s,
            values=depth,
            source=DepthSource.RGBD,
            native_mode=DepthMode.METRIC,
        ),
        target_depth=TargetDepth(depth_value, 1.0, 1.0, 6400, 6400),
        centroid_xyz=np.array([0.0, 0.0, depth_value]),
        target_point_cloud=points,
        camera_intrinsics=IntrinsicsObservation(
            CameraIntrinsics(width=100, height=100, fx=500.0, fy=500.0, cx=49.5, cy=49.5),
            IntrinsicsSource.NOMINAL_FOV,
            CalibrationState.UNCALIBRATED,
            nominal_fov_deg=75.0,
        ),
        depth_source=DepthSource.RGBD,
        depth_mode=DepthMode.APPROX_METRIC,
        inference_time_s=0.01,
        geometry_sanity=GeometrySanity(
            GeometrySanityStatus.PASS,
            ("SAME_SNAPSHOT_COORDINATES", "FINITE_TARGET_POINT_CLOUD"),
        ),
    )


class FakeMapDetector:
    def __init__(self, widths: tuple[float, ...] = (100.0, 40.0, 35.0, 32.0, 30.0)) -> None:
        self.widths = widths
        self.calls = 0

    def infer(self, snapshot, observation, progress=None) -> GraspMaps:
        self.calls += 1
        quality = np.zeros((100, 100), dtype=np.float32)
        angle = np.zeros((100, 100), dtype=np.float32)
        width = np.zeros((100, 100), dtype=np.float32)
        peaks = ((50, 50), (30, 30), (70, 30), (30, 70), (70, 70))
        scores = (0.95, 0.91, 0.88, 0.84, 0.81)
        for (row, column), score, candidate_width in zip(peaks, scores, self.widths):
            quality[row, column] = score
            angle[row, column] = 0.2
            width[row, column] = candidate_width
        return GraspMaps(
            quality,
            angle,
            width,
            (0, 0, 100, 100),
            (224, 224),
            0.012,
            0.05 if self.calls == 1 else 0.0,
            self.calls > 1,
            "CPU",
            "TEST_VERIFIED",
        )


class TopKPlannerTests(unittest.TestCase):
    def test_highest_quality_incompatible_candidate_does_not_fail_plan(self) -> None:
        detector = FakeMapDetector()
        planner = PixelWiseTopKGraspPlanner(
            detector,
            TopKGraspPlannerConfig(top_k=5, minimum_mask_margin_ratio=0.0),
        )
        outcome = planner.plan(make_observation(), make_snapshot())
        self.assertTrue(outcome.ready)
        self.assertEqual(len(outcome.candidates), 5)
        rejected_best_q = max(outcome.candidates, key=lambda candidate: candidate.quality_score)
        self.assertFalse(rejected_best_q.executable)
        self.assertIn("GRIPPER_TOO_WIDE", rejected_best_q.rejection_reasons)
        self.assertIsNotNone(outcome.plan)
        assert outcome.plan is not None
        self.assertNotEqual(outcome.plan.best_candidate_id, rejected_best_q.candidate_id)
        best = next(
            candidate
            for candidate in outcome.candidates
            if candidate.candidate_id == outcome.plan.best_candidate_id
        )
        self.assertTrue(best.executable)
        executable = [candidate for candidate in outcome.candidates if candidate.executable]
        self.assertAlmostEqual(
            best.ranking_score,
            max(candidate.ranking_score for candidate in executable),
            places=7,
        )
        self.assertLess(best.quality_score, rejected_best_q.quality_score)
        self.assertEqual(outcome.plan.planning_state.value, "GRASP_READY")
        self.assertEqual(outcome.plan.spatial_observation_id, make_observation().geometry_chain_id)
        self.assertEqual(best.public_metadata()["checks"]["collision_feasibility"], "UNKNOWN")

    def test_insufficient_geometry_rejects_every_candidate(self) -> None:
        observation = make_observation()
        sparse = replace(observation, target_point_cloud=observation.target_point_cloud[:10])
        planner = PixelWiseTopKGraspPlanner(
            FakeMapDetector(),
            TopKGraspPlannerConfig(top_k=5, minimum_mask_margin_ratio=0.0),
        )
        outcome = planner.plan(sparse, make_snapshot())
        self.assertFalse(outcome.ready)
        self.assertEqual(outcome.rejection_reason, "INSUFFICIENT_GEOMETRY")
        self.assertTrue(
            all("INSUFFICIENT_GEOMETRY" in item.rejection_reasons for item in outcome.candidates)
        )

    def test_too_wide_is_final_reason_only_when_every_candidate_is_too_wide(self) -> None:
        planner = PixelWiseTopKGraspPlanner(
            FakeMapDetector((100.0, 100.0, 100.0, 100.0, 100.0)),
            TopKGraspPlannerConfig(top_k=5, minimum_mask_margin_ratio=0.0),
        )
        outcome = planner.plan(make_observation(), make_snapshot())
        self.assertFalse(outcome.ready)
        self.assertEqual(outcome.rejection_reason, "GRIPPER_TOO_WIDE")
        self.assertTrue(all(not candidate.executable for candidate in outcome.candidates))
        request = outcome.visualization_request()
        self.assertEqual(request["planning_status"], "PLANNING_REJECTED")
        self.assertEqual(request["candidate_count"], 5)

    def test_low_quality_and_too_narrow_are_both_preserved_in_summary(self) -> None:
        planner = PixelWiseTopKGraspPlanner(
            FakeMapDetector((0.1, 0.1, 0.1, 0.1, 0.1)),
            TopKGraspPlannerConfig(
                top_k=5,
                minimum_quality=1.0,
                minimum_mask_margin_ratio=0.0,
            ),
        )
        outcome = planner.plan(make_observation(), make_snapshot())
        self.assertFalse(outcome.ready)
        self.assertEqual(
            outcome.rejection_reason,
            "LOW_GRASP_QUALITY+GRIPPER_TOO_NARROW",
        )
        self.assertTrue(
            all(
                candidate.rejection_reasons
                == ("LOW_GRASP_QUALITY", "GRIPPER_TOO_NARROW")
                for candidate in outcome.candidates
            )
        )

    def test_research_and_demo_use_identical_maps_and_candidates(self) -> None:
        detector = FakeMapDetector()
        planner = PixelWiseTopKGraspPlanner(
            detector,
            TopKGraspPlannerConfig(top_k=5, minimum_mask_margin_ratio=0.0),
        )
        research = planner.plan(make_observation(), make_snapshot(), mode=PlanningMode.RESEARCH)
        demo = planner.plan(make_observation(), make_snapshot(), mode=PlanningMode.DEMO)
        self.assertEqual(
            [(item.center_uv, item.quality_score, item.rejection_reasons) for item in research.candidates],
            [(item.center_uv, item.quality_score, item.rejection_reasons) for item in demo.candidates],
        )
        self.assertEqual(research.plan.best_candidate_id, demo.plan.best_candidate_id)
        self.assertFalse(research.maps.model_was_ready)
        self.assertTrue(demo.maps.model_was_ready)


class GRConvNetPreprocessingContractTests(unittest.TestCase):
    def test_upstream_preprocessing_keeps_rgbd_context_and_channel_order(self) -> None:
        height = width = 100
        rgb = np.empty((height, width, 3), dtype=np.uint8)
        rgb[:] = (220, 20, 30)
        rgb[20:80, 20:80] = (40, 80, 230)
        mask = np.zeros((height, width), dtype=np.bool_)
        mask[20:80, 20:80] = True
        frame = RGBFrame(72, 13.0, "preprocess-contract", rgb)
        target = TargetInstance(
            instance_id="target-72-01",
            mask=mask,
            bbox_xyxy=(20.0, 20.0, 80.0, 80.0),
            centroid_2d=(49.5, 49.5),
            source_frame_id=72,
            source_timestamp_s=13.0,
        )
        snapshot = TargetSceneSnapshot("snapshot-72", frame, target)
        depth = np.full((height, width), 0.9, dtype=np.float32)
        depth[20:80, 20:80] = 0.7
        base = make_observation(depth_value=0.7)
        observation = replace(
            base,
            snapshot_id=snapshot.snapshot_id,
            geometry_chain_id=snapshot.geometry_chain_id,
            source_frame_id=frame.frame_id,
            source_timestamp_s=frame.timestamp_s,
            target_instance_id=target.instance_id,
            depth_frame=DepthFrame(
                source_frame_id=frame.frame_id,
                source_timestamp_s=frame.timestamp_s,
                values=depth,
                source=DepthSource.RGBD,
                native_mode=DepthMode.METRIC,
            ),
            target_depth=TargetDepth(0.7, 1.0, 1.0, 3600, 3600),
        )
        detector = GRConvNetDetector()
        with self.assertLogs(
            "vision2grasp.grasp_planning.detector", level="DEBUG"
        ) as captured:
            tensor, crop = detector._prepare_input(snapshot, observation)

        self.assertEqual(crop, (9, 9, 90, 90))
        self.assertEqual(tuple(tensor.shape), (1, 4, 224, 224))
        self.assertEqual(tensor.dtype, __import__("torch").float32)
        values = tensor.numpy()[0]
        # Context remains present: red dominates outside the target while blue
        # dominates inside it. The first channel is numeric normalized depth.
        self.assertGreater(values[1, 15, 112], values[3, 15, 112])
        self.assertGreater(values[3, 112, 112], values[1, 112, 112])
        self.assertGreater(values[0, 15, 112], values[0, 112, 112])
        self.assertIn("model_input_channel_order", " ".join(captured.output))


class GraspPlanningJobTests(unittest.TestCase):
    @staticmethod
    def wait(service: GraspPlanningService) -> dict[str, object]:
        deadline = time.monotonic() + 3.0
        state = service.snapshot()
        while state["status"] == "PLANNING" and time.monotonic() < deadline:
            time.sleep(0.01)
            state = service.snapshot()
        return state

    def test_async_job_exposes_maps_candidates_preflight_and_views(self) -> None:
        planner = PixelWiseTopKGraspPlanner(
            FakeMapDetector(),
            TopKGraspPlannerConfig(top_k=5, minimum_mask_margin_ratio=0.0),
        )
        service = GraspPlanningService(planner)
        started = service.plan(make_observation(), make_snapshot(), mode="DEMO")
        self.assertEqual(started["status"], "PLANNING")
        self.assertIsNotNone(started["job_id"])
        state = self.wait(service)
        self.assertEqual(state["status"], "GRASP_READY")
        self.assertEqual(state["stage"], "GRASP_READY")
        self.assertTrue(state["preflight"]["graspable"])
        self.assertEqual(set(state["media"]["available_layers"]), {"quality", "angle", "width", "candidates"})
        for layer in state["media"]["available_layers"]:
            self.assertGreater(len(service.view_jpeg(layer) or b""), 100)

    def test_rejected_job_exposes_deterministic_simulation_attempt_candidate(self) -> None:
        service = GraspPlanningService(
            PixelWiseTopKGraspPlanner(
                FakeMapDetector((100.0, 100.0, 100.0, 100.0, 100.0)),
                TopKGraspPlannerConfig(top_k=5, minimum_mask_margin_ratio=0.0),
            )
        )
        service.plan(make_observation(), make_snapshot(), mode="RESEARCH")
        state = self.wait(service)
        self.assertEqual(state["status"], "PLANNING_REJECTED")
        self.assertEqual(state["error_code"], "GRIPPER_TOO_WIDE")
        self.assertTrue(state["simulation_attempt"]["available"])
        self.assertEqual(state["simulation_attempt"]["state"], "READY")
        self.assertEqual(
            state["simulation_attempt"]["candidate_id"],
            state["candidates"][0]["candidate_id"],
        )
        self.assertEqual(
            service.current_outcome().object_extents_xyz.tolist(),
            state["visualization_request"]["object_extents_xyz"],
        )

    def test_reset_invalidates_late_job_result(self) -> None:
        planner = PixelWiseTopKGraspPlanner(
            FakeMapDetector(),
            TopKGraspPlannerConfig(top_k=5, minimum_mask_margin_ratio=0.0),
        )
        service = GraspPlanningService(planner)
        service.plan(make_observation(), make_snapshot())
        reset = service.reset()
        self.assertEqual(reset["status"], "WAITING")
        time.sleep(0.1)
        self.assertEqual(service.snapshot()["status"], "WAITING")

    def test_http_plan_is_accepted_then_exposes_state_and_layer(self) -> None:
        service = GraspPlanningService(
            PixelWiseTopKGraspPlanner(
                FakeMapDetector(),
                TopKGraspPlannerConfig(top_k=5, minimum_mask_margin_ratio=0.0),
            )
        )

        class _App:
            grasp_planning = service

            @staticmethod
            def plan_grasp(body: dict[str, object]) -> dict[str, object]:
                return service.plan(make_observation(), make_snapshot(), mode=str(body["mode"]))

        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(AppRequestHandler, app=_App()),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        try:
            request = Request(
                f"{base_url}/api/grasp-planning/plan",
                data=json.dumps({"snapshot_id": "snapshot-71", "mode": "DEMO"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, HTTPStatus.ACCEPTED)
                started = json.load(response)
            self.assertEqual(started["status"], "PLANNING")
            state = self.wait(service)
            self.assertEqual(state["status"], "GRASP_READY")
            with urlopen(
                f"{base_url}/api/grasp-planning/view.jpg?layer=quality",
                timeout=3,
            ) as response:
                self.assertEqual(response.headers.get_content_type(), "image/jpeg")
                self.assertGreater(len(response.read()), 100)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


@unittest.skipUnless(
    any(verify_model_file(path, GRCONVNET_MODEL_ASSET) for path in GRCONVNET_PROJECT_COMPATIBLE_PATHS),
    "official verified GR-ConvNet checkpoint is not present",
)
class OfficialGraspCheckpointSmokeTest(unittest.TestCase):
    def test_verified_checkpoint_generates_real_quality_angle_and_width_maps(self) -> None:
        from vision2grasp.grasp_planning import GRConvNetDetector

        maps = GRConvNetDetector().infer(make_snapshot(), make_observation())
        self.assertEqual(maps.quality.shape, (100, 100))
        self.assertEqual(maps.angle.shape, maps.quality.shape)
        self.assertEqual(maps.width_px.shape, maps.quality.shape)
        self.assertTrue(np.all(np.isfinite(maps.quality)))
        self.assertGreater(maps.inference_time_s, 0.0)
        self.assertIn(maps.compute_device, {"CPU", "CUDA"})


@unittest.skipUnless(
    (PROJECT_ROOT / "artifacts" / "models" / "FastSAM-s.pt").is_file()
    and verify_model_file(
        default_user_model_cache() / DEPTH_MODEL_ASSET.relative_path,
        DEPTH_MODEL_ASSET,
    )
    and any(
        verify_model_file(path, GRCONVNET_MODEL_ASSET)
        for path in GRCONVNET_PROJECT_COMPATIBLE_PATHS
    ),
    "verified FastSAM, Depth Anything, and GR-ConvNet assets are required",
)
class OfficialEndToEndGraspChainTest(unittest.TestCase):
    def test_cc0_bottle_reaches_real_topk_grasp_ready(self) -> None:
        bgr = cv2.imread(str(PROJECT_ROOT / "artifacts" / "perception" / "bottle_cc0.jpg"))
        self.assertIsNotNone(bgr)
        bgr = cv2.resize(bgr, (518, 518), interpolation=cv2.INTER_AREA)
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        frame = RGBFrame(600, 600.0, "grasp-v06-integration", rgb)
        target_service = TargetPerceptionService(
            FastSAMTargetSegmenter(FastSAMTargetSegmenterConfig(allow_download=False))
        )
        analyzed = target_service.analyze(frame)
        self.assertGreater(len(analyzed["candidates"]), 0)
        target_service.select(
            str(analyzed["candidates"][0]["id"]),
            source_frame_id=frame.frame_id,
        )
        snapshot = target_service.selected_scene_snapshot()
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        observation = MaskSpatialPerceptionProvider(
            MonocularDepthProvider(),
            NominalFOVCameraIntrinsicsProvider(),
        ).analyze(snapshot)
        from vision2grasp.grasp_planning import GRConvNetDetector

        outcome = PixelWiseTopKGraspPlanner(GRConvNetDetector()).plan(observation, snapshot)
        self.assertTrue(outcome.ready)
        self.assertEqual(len(outcome.candidates), 8)
        self.assertGreaterEqual(sum(item.executable for item in outcome.candidates), 1)
        self.assertIsNotNone(outcome.plan)
        assert outcome.plan is not None
        self.assertEqual(outcome.plan.snapshot_id, snapshot.snapshot_id)
        self.assertEqual(outcome.plan.spatial_observation_id, observation.geometry_chain_id)
        self.assertIn(outcome.plan.model_metadata["compute_device"], {"CPU", "CUDA"})


if __name__ == "__main__":
    unittest.main()
