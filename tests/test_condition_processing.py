from __future__ import annotations

import unittest

import cv2
import numpy as np

from run_vision2grasp_app import Vision2GraspApp

from vision2grasp.condition_processing import (
    ConditionExperimentProcessor,
    ConditionProcessor,
    ConditionProtocol,
    ConditionStressSimulator,
    GraspUncertainty,
    PerceptionUncertainty,
    ReliabilityLevel,
    SpatialUncertainty,
    StressBlurType,
    StressLevel,
    StressStrategy,
)
from vision2grasp.contracts import RGBFrame
from vision2grasp.grasp_planning import CandidateFeasibility, GraspCandidate
from vision2grasp.simulation import SimulationAttempt, ValidationRequest
from vision2grasp.spatial_perception import (
    MaskSpatialPerceptionProvider,
    NominalFOVCameraIntrinsicsProvider,
)
from vision2grasp.spatial_perception.contracts import DepthFrame, DepthMode, DepthSource
from vision2grasp.target_perception import (
    TargetInstance,
    TargetPerceptionService,
    TargetSceneSnapshot,
)


def checkerboard(*, dark: bool = False) -> np.ndarray:
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    for y in range(0, 120, 10):
        for x in range(0, 160, 10):
            image[y : y + 10, x : x + 10] = 240 if (x // 10 + y // 10) % 2 else 30
    if dark:
        image = np.rint(image.astype(np.float32) * 0.10).astype(np.uint8)
    return image


class _WholeFrameSegmenter:
    def predict(self, frame: RGBFrame):
        height, width = frame.rgb.shape[:2]
        mask = np.ones((height, width), dtype=np.bool_)
        return (
            TargetInstance(
                "target-condition-01",
                mask,
                (0.0, 0.0, float(width), float(height)),
                ((width - 1) / 2.0, (height - 1) / 2.0),
                frame.frame_id,
                frame.timestamp_s,
                confidence=0.72,
            ),
        )


class _DepthProvider:
    def infer(self, frame: RGBFrame, progress=None) -> DepthFrame:
        return DepthFrame(
            frame.frame_id,
            frame.timestamp_s,
            np.full(frame.rgb.shape[:2], 0.72, dtype=np.float32),
            DepthSource.MONOCULAR,
            DepthMode.METRIC,
            inference_time_s=0.01,
        )


class ConditionProcessingTests(unittest.TestCase):
    def test_live_preview_uses_pipeline_frame_while_normal_and_demo_are_byte_identical(self) -> None:
        bgr = cv2.cvtColor(checkerboard(), cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(".jpg", bgr)
        self.assertTrue(ok)
        jpeg = encoded.tobytes()
        app = object.__new__(Vision2GraspApp)
        app.condition_experiment = ConditionExperimentProcessor(ConditionProcessor())
        normal = app.process_live_condition_jpeg(
            jpeg, 1, {"condition": "NORMAL", "mode": "RESEARCH"}
        )
        demo = app.process_live_condition_jpeg(
            jpeg, 1, {"condition": "BLUR", "mode": "DEMO"}
        )
        stressed = app.process_live_condition_jpeg(
            jpeg,
            1,
            {
                "condition": "BLUR",
                "mode": "RESEARCH",
                "strategy": "STRESS_ONLY",
                "level": "SEVERE",
                "blur_type": "MOTION",
                "random_seed": 7,
            },
        )
        self.assertIs(normal, jpeg)
        self.assertIs(demo, jpeg)
        self.assertNotEqual(stressed, jpeg)

    def test_stress_normal_is_pixel_identical_and_preserves_all_frame_ids(self) -> None:
        source = checkerboard()
        result = ConditionExperimentProcessor(ConditionProcessor()).process(
            RGBFrame(8, 1.25, "phone", source),
            ConditionProtocol.NORMAL,
            strategy=StressStrategy.STRESS_PLUS_RECOVERY,
            level=StressLevel.SEVERE,
            random_seed=99,
        )
        stress = result.report.stress_test
        self.assertFalse(stress.applied)
        self.assertEqual(
            {stress.raw_frame_id, stress.degraded_frame_id, stress.pipeline_frame_id},
            {8},
        )
        np.testing.assert_array_equal(result.source_frame.rgb, source)
        np.testing.assert_array_equal(result.degraded_frame.rgb, source)
        np.testing.assert_array_equal(result.processed_frame.rgb, source)

    def test_low_light_stress_is_reproducible_and_records_parameters(self) -> None:
        frame = RGBFrame(9, 1.5, "phone", checkerboard())
        simulator = ConditionStressSimulator()
        first = simulator.simulate(
            frame,
            ConditionProtocol.LOW_LIGHT,
            level=StressLevel.SEVERE,
            random_seed=123,
        )
        second = simulator.simulate(
            frame,
            ConditionProtocol.LOW_LIGHT,
            level=StressLevel.SEVERE,
            random_seed=123,
        )
        changed_seed = simulator.simulate(
            frame,
            ConditionProtocol.LOW_LIGHT,
            level=StressLevel.SEVERE,
            random_seed=124,
        )
        np.testing.assert_array_equal(first.degraded_frame.rgb, second.degraded_frame.rgb)
        self.assertNotEqual(first.degraded_sha256, changed_seed.degraded_sha256)
        self.assertLess(float(np.mean(first.degraded_frame.rgb)), float(np.mean(frame.rgb)))
        self.assertEqual(
            first.degradation_chain,
            ("BRIGHTNESS_REDUCTION", "CONTRAST_REDUCTION", "SHADOW_NOISE"),
        )
        self.assertEqual(first.parameters["brightness"], 0.25)
        self.assertEqual(first.parameters["contrast"], 0.46)
        self.assertEqual(first.parameters["noise_sigma"], 16.0)

    def test_gaussian_and_motion_blur_are_distinct_deterministic_stressors(self) -> None:
        frame = RGBFrame(11, 2.0, "phone", checkerboard())
        simulator = ConditionStressSimulator()
        gaussian = simulator.simulate(
            frame,
            ConditionProtocol.BLUR,
            blur_type=StressBlurType.GAUSSIAN,
            level=StressLevel.MODERATE,
        )
        motion = simulator.simulate(
            frame,
            ConditionProtocol.BLUR,
            blur_type=StressBlurType.MOTION,
            level=StressLevel.MODERATE,
        )
        self.assertIn("GAUSSIAN_BLUR", gaussian.degradation_chain)
        self.assertIn("MOTION_BLUR", motion.degradation_chain)
        self.assertNotEqual(gaussian.degraded_sha256, motion.degraded_sha256)
        self.assertEqual(gaussian.parameters["gaussian_kernel"], 11)
        self.assertEqual(motion.parameters["motion_length"], 11)

    def test_stress_plus_recovery_records_complete_immutable_frame_chain(self) -> None:
        result = ConditionExperimentProcessor(ConditionProcessor()).process(
            RGBFrame(12, 2.5, "phone", checkerboard()),
            ConditionProtocol.LOW_LIGHT_BLUR,
            strategy=StressStrategy.STRESS_PLUS_RECOVERY,
            level=StressLevel.MODERATE,
            blur_type=StressBlurType.MOTION,
            random_seed=77,
        )
        metadata = result.report.public_metadata()["stress_test"]
        self.assertEqual(metadata["strategy"], "STRESS_PLUS_RECOVERY")
        self.assertEqual(metadata["random_seed"], 77)
        self.assertEqual(metadata["frames"]["raw"]["frame_id"], 12)
        self.assertEqual(
            metadata["frames"]["pipeline"]["frame_id"], result.processed_frame.frame_id
        )
        self.assertNotEqual(result.source_frame.frame_id, result.degraded_frame.frame_id)
        for experiment_frame in (
            result.source_frame,
            result.degraded_frame,
            result.processed_frame,
        ):
            self.assertFalse(experiment_frame.rgb.flags.writeable)
        if result.enhanced_frame is not None:
            self.assertFalse(result.enhanced_frame.rgb.flags.writeable)
            self.assertEqual(
                metadata["frames"]["enhanced"]["frame_id"],
                result.enhanced_frame.frame_id,
            )

    def test_normal_is_assessment_only_and_preserves_immutable_raw_provenance(self) -> None:
        pixels = checkerboard()
        original = pixels.copy()
        result = ConditionProcessor().process(RGBFrame(10, 2.5, "phone", pixels), "NORMAL")

        np.testing.assert_array_equal(pixels, original)
        np.testing.assert_array_equal(result.raw_frame.rgb, original)
        np.testing.assert_array_equal(result.processed_frame.rgb, original)
        self.assertFalse(result.raw_frame.rgb.flags.writeable)
        self.assertFalse(result.processed_frame.rgb.flags.writeable)
        self.assertEqual(result.report.raw_frame_id, result.report.processed_frame_id)
        self.assertFalse(result.report.enhancement_applied)
        self.assertEqual(result.report.enhancement_status.value, "ASSESSMENT_ONLY")

    def test_blur_and_brightness_scores_have_documented_directions(self) -> None:
        processor = ConditionProcessor()
        sharp = checkerboard()
        blurred = cv2.GaussianBlur(sharp, (25, 25), 7.0)
        dark = checkerboard(dark=True)
        sharp_report = processor.process(RGBFrame(1, 1.0, "phone", sharp)).report
        blur_report = processor.process(RGBFrame(2, 2.0, "phone", blurred)).report
        dark_report = processor.process(RGBFrame(3, 3.0, "phone", dark)).report

        self.assertGreater(blur_report.blur_score, sharp_report.blur_score)
        self.assertLess(dark_report.brightness_score, sharp_report.brightness_score)
        self.assertEqual(dark_report.visual_condition.value, "LOW_LIGHT")
        self.assertIn(dark_report.reliability.value, {"LOW", "MEDIUM"})

    def test_combined_protocol_records_ordered_chain_and_never_synthesizes_degradation(self) -> None:
        source = cv2.GaussianBlur(checkerboard(dark=True), (25, 25), 7.0)
        original = source.copy()
        result = ConditionProcessor().process(
            RGBFrame(20, 4.0, "phone", source),
            ConditionProtocol.LOW_LIGHT_BLUR,
        )

        np.testing.assert_array_equal(source, original)
        self.assertEqual(
            result.report.enhancement_chain,
            ("EXPOSURE_RECOVERY_CLAHE", "MILD_DENOISE_BILATERAL", "UNSHARP_MASK"),
        )
        if result.report.enhancement_applied:
            self.assertNotEqual(result.report.raw_frame_id, result.report.processed_frame_id)
            self.assertGreaterEqual(result.report.after_quality, result.report.before_quality)
        else:
            self.assertEqual(result.report.raw_frame_id, result.report.processed_frame_id)
            np.testing.assert_array_equal(result.processed_frame.rgb, result.raw_frame.rgb)

    def test_target_and_spatial_layers_propagate_condition_and_uncertainty(self) -> None:
        conditioned = ConditionExperimentProcessor(ConditionProcessor()).process(
            RGBFrame(30, 5.0, "phone", checkerboard(dark=True)),
            ConditionProtocol.LOW_LIGHT,
            strategy=StressStrategy.STRESS_ONLY,
            level=StressLevel.MILD,
            random_seed=31,
        )
        service = TargetPerceptionService(_WholeFrameSegmenter())
        analyzed = service.analyze(conditioned)
        self.assertEqual(analyzed["condition_report"]["report_id"], conditioned.report.report_id)
        service.select("target-condition-01", source_frame_id=conditioned.processed_frame.frame_id)
        snapshot = service.selected_scene_snapshot()
        self.assertEqual(snapshot.raw_frame.frame_id, conditioned.source_frame.frame_id)
        self.assertEqual(snapshot.degraded_frame.frame_id, conditioned.degraded_frame.frame_id)
        self.assertEqual(snapshot.condition_report.report_id, conditioned.report.report_id)
        self.assertEqual(snapshot.perception_uncertainty.stage, "TARGET_PERCEPTION")

        observation = MaskSpatialPerceptionProvider(
            _DepthProvider(), NominalFOVCameraIntrinsicsProvider()
        ).analyze(snapshot)
        metadata = observation.public_metadata()
        self.assertEqual(metadata["condition_report"]["report_id"], conditioned.report.report_id)
        self.assertEqual(metadata["spatial_uncertainty"]["stage"], "SPATIAL_PERCEPTION")
        self.assertEqual(metadata["source_frame_id"], conditioned.processed_frame.frame_id)

    def test_validation_context_keeps_condition_warnings_separate_from_physics(self) -> None:
        conditioned = ConditionExperimentProcessor(ConditionProcessor()).process(
            RGBFrame(40, 6.0, "phone", np.zeros((48, 64, 3), dtype=np.uint8)),
            ConditionProtocol.LOW_LIGHT_BLUR,
            strategy=StressStrategy.STRESS_ONLY,
            level=StressLevel.SEVERE,
            random_seed=2026,
        )
        report = conditioned.report
        perception = PerceptionUncertainty(
            "TARGET_PERCEPTION", report.report_id, ReliabilityLevel.LOW, None, ("PERCEPTION_UNCERTAIN",)
        )
        spatial = SpatialUncertainty(
            "SPATIAL_PERCEPTION", report.report_id, ReliabilityLevel.LOW, 0.2, ("DEPTH_UNRELIABLE",)
        )
        grasp = GraspUncertainty(
            "GRASP_PLANNING", report.report_id, ReliabilityLevel.LOW, 0.18, ("LOW_IMAGE_QUALITY",)
        )
        candidate = GraspCandidate(
            "candidate-01",
            np.array([0.0, 0.0, 0.7]),
            np.array([0.0, 0.0, -1.0]),
            np.array([1.0, 0.0, 0.0]),
            0.0,
            0.09,
            0.18,
            {"quality": 0.18},
            ranking_score=0.18,
            feasibility=CandidateFeasibility.REJECTED,
            rejection_reasons=("GRIPPER_TOO_WIDE",),
            source_frame_id=conditioned.processed_frame.frame_id,
            target_instance_id="target-40",
        )
        attempt = SimulationAttempt.from_rejected_candidate(
            candidate,
            snapshot_id="snapshot-40",
            object_extents_xyz=np.array([0.08, 0.10, 0.04]),
            candidate_count=1,
            planning_reason="GRIPPER_TOO_WIDE",
            minimum_gripper_width_m=0.01,
            maximum_gripper_width_m=0.08,
        )
        request = ValidationRequest.from_grasp_plan(
            attempt,
            condition_report=report,
            perception_uncertainty=perception,
            spatial_uncertainty=spatial,
            grasp_uncertainty=grasp,
        )
        metadata = request.public_metadata()
        self.assertEqual(metadata["planning_result"]["reason"], "GRIPPER_TOO_WIDE")
        self.assertEqual(
            metadata["condition_context"]["condition_report"]["stress_test"]["random_seed"],
            2026,
        )
        self.assertEqual(
            set(metadata["planning_result"]["condition_warnings"]),
            {"PERCEPTION_UNCERTAIN", "DEPTH_UNRELIABLE", "LOW_IMAGE_QUALITY"},
        )
        self.assertEqual(metadata["condition_context"]["effect_on_physics_result"], "CONTEXT_ONLY")
        self.assertEqual(
            set(metadata["condition_context"]["warnings"]),
            {"PERCEPTION_UNCERTAIN", "DEPTH_UNRELIABLE", "LOW_IMAGE_QUALITY"},
        )


if __name__ == "__main__":
    unittest.main()
