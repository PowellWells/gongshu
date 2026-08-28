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
            "startGraspButton",
            "targetStatus",
            "spatialInspectorStatus",
            "graspInspectorStatus",
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
            "当前目标 <b>Target</b>",
            "空间信息 <b>Spatial</b>",
            "抓取结果 <b>Grasp</b>",
            "系统状态 <b>Status</b>",
        ):
            self.assertIn(label, self.html)
        for forbidden in ("YOLO11n-seg", "GR-ConvNet", "Depth Model", "SPANet", "VERGNet", "KufeNet"):
            self.assertNotIn(forbidden.lower(), self.html.lower())

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

    def test_pipeline_declares_all_states_and_stage_driven_views(self) -> None:
        for state in (
            "LIVE",
            "TARGET_SELECTED",
            "SCENE_CAPTURED",
            "SPATIAL_ANALYSIS",
            "GRASP_PLANNING",
            "SCENE_SYNC",
            "SIMULATION",
            "VERIFIED",
            "RESET",
        ):
            self.assertIn(f'"{state}"', self.pipeline)
        self.assertIn('SPATIAL_ANALYSIS: "spatial"', self.pipeline)
        self.assertIn('GRASP_PLANNING: "grasp"', self.pipeline)
        self.assertIn('SIMULATION: "simulation"', self.pipeline)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for the frontend state-machine test")
    def test_pipeline_rejects_invalid_transitions_and_resets_to_live(self) -> None:
        script = r"""
const { PipelineStateMachine } = require(process.argv[1]);
const pipeline = new PipelineStateMachine();
pipeline.transition("SCENE_CAPTURED");
pipeline.transition("SPATIAL_ANALYSIS");
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


if __name__ == "__main__":
    unittest.main()
