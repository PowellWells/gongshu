from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GONGSHU_ROOT = PROJECT_ROOT / "frontend" / "apps" / "gongshu"


class _WorkspaceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.views: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(str(attributes["id"]))
        if attributes.get("data-view"):
            self.views.append(str(attributes["data-view"]))


class GongshuWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (GONGSHU_ROOT / "index.html").read_text(encoding="utf-8")
        cls.controller = (GONGSHU_ROOT / "real-scene.js").read_text(encoding="utf-8")
        cls.pipeline = (GONGSHU_ROOT / "pipeline-state.js").read_text(encoding="utf-8")
        cls.target_selection = (GONGSHU_ROOT / "target-selection.js").read_text(encoding="utf-8")
        cls.parser = _WorkspaceParser()
        cls.parser.feed(cls.html)

    def test_single_workspace_contains_exactly_four_persistent_views(self) -> None:
        self.assertEqual(self.parser.views, ["live", "spatial", "grasp", "simulation"])
        self.assertIn('id="livePanel" class="workspace-view is-primary"', self.html)
        self.assertNotIn("cameraInputShell", self.html)
        self.assertNotIn("realSceneShell", self.html)
        self.assertNotIn("simulationShell", self.html)

    def test_workspace_has_required_controls_and_fixed_inspector_sections(self) -> None:
        required_ids = {
            "sourceSelect",
            "conditionSelect",
            "robotSelect",
            "viewModeSelect",
            "graspModeSelect",
            "analyzeTargetsButton",
            "startGraspButton",
            "targetOverlay",
            "resumeLiveButton",
            "targetStatus",
            "targetClassValue",
            "targetConfidenceValue",
            "targetLockValue",
            "spatialInspectorStatus",
            "spatialMediaLabels",
            "spatialDepthValue",
            "spatialSourceValue",
            "spatialModeValue",
            "spatialProjectionValue",
            "spatialElapsed",
            "spatialModelState",
            "spatialTimingSummary",
            "spatialModelLoadTiming",
            "spatialDepthTiming",
            "spatialPointCloudTiming",
            "spatialTotalTiming",
            "retrySpatialButton",
            "newSceneButton",
            "graspInspectorStatus",
            "graspLayerControls",
            "graspElapsed",
            "graspEta",
            "graspAngleValue",
            "graspWidthValue",
            "graspQualityValue",
            "graspApproachValue",
            "graspFrameValue",
            "startValidationButton",
            "simulationHud",
            "simulationHudState",
            "simulationAppearance",
            "simulationTexture",
            "simulationAppearanceSource",
            "systemStatus",
            "cameraSetupDialog",
            "legacyDialog",
        }
        self.assertTrue(required_ids.issubset(set(self.parser.ids)))
        self.assertEqual(len(self.parser.ids), len(set(self.parser.ids)))

    def test_main_ui_uses_bilingual_function_names_without_model_branding(self) -> None:
        for label in (
            "实时视觉 <b>Live RGB</b>",
            "空间感知 <b>Spatial Perception</b>",
            "抓取规划 <b>Grasp Planning</b>",
            "仿真验证 <b>MuJoCo Validation</b>",
            'id="validationScenarioSelect"',
            "TARGET_OFFSET_STRESS",
            "当前目标 <b>Target</b>",
            "空间信息 <b>Spatial</b>",
            "抓取结果 <b>Grasp</b>",
            "系统状态 <b>Status</b>",
        ):
            self.assertIn(label, self.html)
        for forbidden in (
            "YOLO11n-seg",
            "GR-ConvNet",
            "Depth Model",
            "SPANet",
            "VERGNet",
            "KufeNet",
            "Pinhole Camera",
            "针孔相机",
            "超微型相机",
        ):
            self.assertNotIn(forbidden.lower(), self.html.lower())
            self.assertNotIn(forbidden.lower(), self.controller.lower())

    def test_phone_camera_api_and_pairing_controls_are_reused(self) -> None:
        for endpoint in (
            "/api/camera/state",
            "/api/camera/live.mjpeg",
            "/api/camera/pairing/refresh",
            "/api/camera/capture/save",
        ):
            self.assertIn(endpoint, self.controller)
        for element_id in (
            "pairingQr",
            "setupQr",
            "refreshPairingButton",
            "captureImage",
            "saveCaptureButton",
        ):
            self.assertIn(f'id="{element_id}"', self.html)

    def test_target_analysis_uses_frozen_backend_frame_and_manual_selection(self) -> None:
        for endpoint in (
            "/api/target-perception/analyze",
            "/api/target-perception/select",
            "/api/target-perception/select-at",
            "/api/target-perception/reset",
            "/api/target-perception/overlay.jpg",
            "/api/target-perception/scene-snapshot.jpg",
            "/api/spatial-perception/analyze",
            "/api/spatial-perception/retry",
            "/api/spatial-perception/state",
            "/api/spatial-perception/overview.jpg",
            "/api/grasp-planning/plan",
            "/api/grasp-planning/overlay.jpg",
            "/api/grasp-planning/view.jpg",
            "/api/mujoco-validation/start",
            "/api/mujoco-validation/live.mjpeg",
            "/api/mujoco-validation/state",
            "/api/mujoco-validation/playback",
            "/api/mujoco-validation/recording/save",
            "/api/mujoco-validation/export-video",
            "/api/mujoco-validation/history",
        ):
            self.assertIn(endpoint, self.controller)
        self.assertIn('pipeline.transition("TARGET_SELECTED"', self.controller)
        self.assertIn('pipeline.transition("SCENE_CAPTURED"', self.controller)
        self.assertIn('pipeline.transition("SPATIAL_ANALYSIS"', self.controller)
        self.assertIn('addEventListener("pointerdown", selectTargetAtPointer)', self.controller)
        self.assertIn('preserveAspectRatio", "xMidYMid meet"', self.controller)
        self.assertIn('targetOverlay.removeAttribute("hidden")', self.controller)
        self.assertNotIn("targetOverlay.hidden = false", self.controller)
        self.assertNotIn("captureLiveFrame", self.controller)
        self.assertNotIn("canvas.toBlob", self.controller)
        self.assertIn("state?.stage_message", self.controller)
        self.assertIn("state?.total_elapsed_s", self.controller)
        self.assertIn("state?.eta?.estimated_remaining_s", self.controller)
        self.assertIn("waitForSpatialJob", self.controller)
        self.assertIn("waitForGraspJob", self.controller)
        self.assertIn("await runGraspPlanning();", self.controller)
        self.assertIn('mode: els.graspModeSelect.value', self.controller)
        self.assertIn('"GRASP_READY", "PLANNING_REJECTED", "GRASP_ERROR"', self.controller)
        self.assertIn("state.job_id !== jobId", self.controller)
        self.assertIn("monitorRestoredSpatialJob", self.controller)
        self.assertIn("bytes_downloaded", self.controller)
        self.assertNotIn("setInterval(pollSpatialAnalysisState", self.controller)
        self.assertNotIn("0–100", self.html)
        self.assertIn("请选择目标", self.html)

    def test_recording_playback_is_explicit_session_first_ui(self) -> None:
        for element_id in (
            "simulationPlaybackControls", "playbackTimeline", "playPauseButton",
            "saveRecordingButton", "exportVideoButton", "technicalOverlayToggle",
            "sessionHistoryList", "savedRunsList",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        for camera in ("AUTO_CINEMATIC", "TECHNICAL", "TARGET_FOLLOW", "FREE_CAMERA"):
            self.assertIn(f'data-sim-camera="{camera}"', self.html)
        for speed in ("0.25", "0.5", "1", "2"):
            self.assertIn(f'data-playback-speed="{speed}"', self.html)
        self.assertIn("Replay Available", self.html)
        self.assertIn("Unsaved", self.html)
        self.assertIn("未保存项目在退出应用后丢弃", self.html)
        self.assertIn("外观 Appearance", self.html)
        self.assertIn("纹理 Texture", self.html)
        self.assertIn("来源 Source", self.html)
        self.assertIn("APPEARANCE FALLBACK", self.controller)
        self.assertIn("Target Snapshot Frame", self.controller)
        self.assertIn("target_appearance", self.controller)

    def test_pipeline_declares_all_states_and_stage_driven_views(self) -> None:
        for state in (
            "LIVE",
            "TARGET_SELECTED",
            "SCENE_CAPTURED",
            "SPATIAL_ANALYSIS",
            "SPATIAL_READY",
            "GRASP_PLANNING",
            "SCENE_SYNC",
            "SIMULATION",
            "VERIFIED",
            "RESET",
        ):
            self.assertIn(f'"{state}"', self.pipeline)
        self.assertIn('SPATIAL_ANALYSIS: "spatial"', self.pipeline)
        self.assertIn('SPATIAL_READY: "spatial"', self.pipeline)
        self.assertIn('GRASP_PLANNING: "grasp"', self.pipeline)
        self.assertIn('SIMULATION: "simulation"', self.pipeline)
        self.assertIn('SPATIAL_READY: new Set(["GRASP_PLANNING", "RESET"])', self.pipeline)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the frontend state-machine test")
    def test_pipeline_rejects_invalid_transitions_and_resets_to_live(self) -> None:
        script = r"""
const { PipelineStateMachine } = require(process.argv[1]);
const pipeline = new PipelineStateMachine();
pipeline.transition("TARGET_SELECTED");
pipeline.transition("SCENE_CAPTURED");
pipeline.transition("SPATIAL_ANALYSIS");
pipeline.transition("SPATIAL_READY");
let rejected = false;
try { pipeline.transition("SIMULATION"); } catch (_) { rejected = true; }
pipeline.reset({ reason: "test" });
process.stdout.write(JSON.stringify({ rejected, state: pipeline.state, view: pipeline.primaryView() }));
"""
        completed = subprocess.run(
            ["node", "-e", script, str(GONGSHU_ROOT / "pipeline-state.js")],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(result, {"rejected": True, "state": "LIVE", "view": "live"})

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the frontend target-gating test")
    def test_start_grasp_requires_locked_target_and_exact_snapshot_association(self) -> None:
        script = r"""
const { canStartGrasp } = require(process.argv[1]);
const valid = {
  status: "TARGET_LOCKED",
  frame: { id: 42, timestamp_s: 12.5 },
  selected_target_id: "target-42-01",
  selected_target: { id: "target-42-01", source_frame_id: 42, source_timestamp_s: 12.5 },
  scene_snapshot: { available: true, snapshot_id: "snapshot-42", target_id: "target-42-01", source_frame_id: 42, source_timestamp_s: 12.5 },
};
process.stdout.write(JSON.stringify({
  liveRejected: canStartGrasp("LIVE", valid),
  valid: canStartGrasp("TARGET_SELECTED", valid),
  mismatchedFrameRejected: canStartGrasp("TARGET_SELECTED", {
    ...valid,
    scene_snapshot: { ...valid.scene_snapshot, source_frame_id: 41 },
  }),
  missingTargetRejected: canStartGrasp("TARGET_SELECTED", {
    ...valid,
    selected_target: null,
  }),
}));
"""
        completed = subprocess.run(
            ["node", "-e", script, str(GONGSHU_ROOT / "pipeline-state.js")],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {
                "liveRejected": False,
                "valid": True,
                "mismatchedFrameRejected": False,
                "missingTargetRejected": False,
            },
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for spatial association tests")
    def test_spatial_ready_requires_exact_frozen_snapshot_association(self) -> None:
        script = r"""
const { hasSpatialObservationAssociation } = require(process.argv[1]);
const target = {
  scene_snapshot: {
    available: true,
    snapshot_id: "snapshot-42",
    geometry_chain_id: "geometry-42",
    target_id: "target-42-01",
    source_frame_id: 42,
    source_timestamp_s: 12.5,
  },
};
const ready = {
  status: "READY",
  observation: {
    snapshot_id: "snapshot-42",
    geometry_chain_id: "geometry-42",
    target_instance_id: "target-42-01",
    source_frame_id: 42,
    source_timestamp_s: 12.5,
  },
};
process.stdout.write(JSON.stringify({
  valid: hasSpatialObservationAssociation(target, ready),
  newLiveFrameRejected: hasSpatialObservationAssociation(target, {
    ...ready,
    observation: { ...ready.observation, source_frame_id: 43 },
  }),
  wrongTargetRejected: hasSpatialObservationAssociation(target, {
    ...ready,
    observation: { ...ready.observation, target_instance_id: "target-42-02" },
  }),
}));
"""
        completed = subprocess.run(
            ["node", "-e", script, str(GONGSHU_ROOT / "pipeline-state.js")],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(completed.stdout),
            {"valid": True, "newLiveFrameRejected": False, "wrongTargetRejected": False},
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for frozen-frame geometry tests")
    def test_portrait_frozen_frame_remains_selectable_when_phone_disconnects(self) -> None:
        script = r"""
const { clientPointToSource, canSelectFrozenTarget, formatOptionalConfidence } = require(process.argv[1]);
const targetState = {
  status: "CANDIDATES",
  frame: { id: 2386, width: 540, height: 960 },
  candidates: [{ id: "target-2386-03" }],
};
const rect = { left: 10, top: 20, width: 1200, height: 800 };
const center = clientPointToSource({ clientX: 610, clientY: 420 }, rect, targetState.frame);
const letterbox = clientPointToSource({ clientX: 100, clientY: 420 }, rect, targetState.frame);
process.stdout.write(JSON.stringify({
  disconnectedStillSelectable: canSelectFrozenTarget("LIVE", targetState),
  center,
  letterbox,
  missingConfidence: formatOptionalConfidence(null),
  realConfidence: formatOptionalConfidence(0.937),
}));
"""
        completed = subprocess.run(
            ["node", "-e", script, str(GONGSHU_ROOT / "target-selection.js")],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        self.assertTrue(result["disconnectedStillSelectable"])
        self.assertAlmostEqual(result["center"]["x"], 270.0)
        self.assertAlmostEqual(result["center"]["y"], 480.0)
        self.assertIsNone(result["letterbox"])
        self.assertIsNone(result["missingConfidence"])
        self.assertEqual(result["realConfidence"], "93.7%")
        self.assertNotIn("const mayStart = phoneLive", self.controller)


if __name__ == "__main__":
    unittest.main()
