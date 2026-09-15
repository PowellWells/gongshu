from __future__ import annotations

import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
import threading
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtWidgets import QApplication

from xuanshu_lab.contracts import WorkspaceKind, WorkspaceSpec, WorkspaceStatus
from xuanshu_lab.registry import WorkspaceRegistry, create_default_registry
from xuanshu_lab.runtime import LocalServiceController, ServiceHealth, _service_environment
from xuanshu_lab.shell import MainWindow


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WorkspaceRegistryTests(unittest.TestCase):
    def test_default_registry_freezes_three_v01_workspaces(self) -> None:
        registry = create_default_registry()
        self.assertEqual([item.workspace_id for item in registry], ["moment", "gongshu", "hetu"])
        self.assertEqual(registry.get("moment").kind, WorkspaceKind.WEB)
        self.assertEqual(registry.get("gongshu").status, WorkspaceStatus.READY)
        self.assertEqual(registry.get("hetu").kind, WorkspaceKind.PREVIEW)
        self.assertIsNone(registry.get("hetu").route)

    def test_registry_rejects_duplicates_and_invalid_web_routes(self) -> None:
        workspace = create_default_registry().get("moment")
        with self.assertRaisesRegex(ValueError, "duplicate workspace"):
            WorkspaceRegistry((workspace, workspace))
        with self.assertRaisesRegex(ValueError, "root-relative"):
            WorkspaceSpec(
                workspace_id="bad",
                name="Bad",
                english_name="Bad",
                category="TEST",
                description="invalid route",
                kind=WorkspaceKind.WEB,
                status=WorkspaceStatus.READY,
                accent="#123456",
                icon_relative_path="icon.png",
                route="relative.html",
            )


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/api/health":
            self.send_error(404)
            return
        payload = json.dumps(
            {
                "schema_version": "vision2grasp.app-health/v1",
                "status": "ok",
                "capabilities": ["camera.phone-lan/v1"],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class LocalServiceControllerTests(unittest.TestCase):
    def test_service_environment_retains_launcher_xiezhi_path(self) -> None:
        inherited = {
            "PYTHONPATH": str(Path("F:/五月花/src")),
            "XIEZHI_ENABLED": "1",
        }
        environment = _service_environment(PROJECT_ROOT, inherited)
        entries = environment["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(entries[0], str((PROJECT_ROOT / "src").resolve()))
        self.assertEqual(entries[1], str(Path("F:/五月花/src")))
        self.assertEqual(environment["XIEZHI_ENABLED"], "1")

    def test_reuses_compatible_running_service_without_owning_it(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            controller = LocalServiceController(
                PROJECT_ROOT,
                port=int(server.server_address[1]),
            )
            health = controller.start(timeout=1)
            self.assertTrue(health.ready)
            self.assertFalse(controller.owns_process)
            controller.stop()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_stop_terminates_only_an_owned_process(self) -> None:
        controller = LocalServiceController(PROJECT_ROOT, port=65500)
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        controller._process = process
        controller.stop()
        self.assertIsNotNone(process.poll())
        self.assertFalse(controller.owns_process)


class _FakeService:
    base_url = "http://127.0.0.1:8765"

    def health(self, *, timeout: float = 0.6) -> ServiceHealth:
        return ServiceHealth(True, "ready")

    def stop(self) -> None:
        return


class DesktopShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_shell_opens_gongshu_with_xiezhi_as_its_only_visible_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(
                str(Path(directory) / "desktop-test.ini"),
                QSettings.Format.IniFormat,
            )
            window = MainWindow(
                PROJECT_ROOT,
                create_default_registry(),
                _FakeService(),  # type: ignore[arg-type]
                settings=settings,
            )
            try:
                self.assertIs(window.centralWidget(), window.web_view)
                self.assertEqual(window.web_view.objectName(), "xuanshuPortal")
                self.assertEqual(window.portal_url, "http://127.0.0.1:8765/index.html")
                self.assertEqual(
                    window.home_url,
                    "http://127.0.0.1:8765/apps/gongshu/index.html?desktop=1&xiezhi=enabled",
                )
                self.assertEqual(window.web_view.url().toString(), window.home_url)
                self.assertFalse(window.log_dock.isVisible())
                self.assertEqual(window.home_action.shortcut().toString(), "Alt+Home")
                self.assertEqual(window.logs_action.shortcut().toString(), "Ctrl+Shift+L")
                self.assertTrue(window.service_ready)

                window.web_view.setUrl(QUrl("http://127.0.0.1:8765/apps/moment/index.html"))
                window.go_home()
                self.assertEqual(window.web_view.url().toString(), window.home_url)
            finally:
                window.close()


class FrontendPortalTests(unittest.TestCase):
    def test_architecture_v2_freezes_xiezhi_as_an_internal_gongshu_capability(self) -> None:
        current = (
            PROJECT_ROOT / "XUANSHU_ARCHITECTURE_FREEZE_V2.0.md"
        ).read_text(encoding="utf-8")
        historical = (
            PROJECT_ROOT / "XUANSHU_ARCHITECTURE_FREEZE_V1.0.md"
        ).read_text(encoding="utf-8")
        launcher = (
            PROJECT_ROOT / "scripts" / "start_xuanshu_lab.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn("Gongshu 是主体，Xiezhi 是能力", current)
        self.assertIn("用户只需要知道“打开 Gongshu”", current)
        self.assertIn("不创建 Xiezhi 独立 App、启动器、产品页或桌面入口", current)
        self.assertIn("当前权威文档：`XUANSHU_ARCHITECTURE_FREEZE_V2.0.md`", historical)
        self.assertIn("internal Xiezhi intelligence capability", launcher)
        self.assertNotIn("optional Xiezhi lifecycle support", launcher)

    def test_xuanshu_cmd_is_the_only_documented_launcher(self) -> None:
        official_cmd = (PROJECT_ROOT / "Start-XUANSHU-LAB.cmd").read_text(
            encoding="utf-8-sig"
        )
        legacy_cmd = (PROJECT_ROOT / "Start-Vision2Grasp.cmd").read_text(
            encoding="utf-8-sig"
        )
        legacy_script = (
            PROJECT_ROOT / "scripts" / "start_vision2grasp.ps1"
        ).read_text(encoding="utf-8-sig")

        self.assertIn(r"scripts\start_xuanshu_lab.ps1", official_cmd)
        self.assertIn("Start-XUANSHU-LAB.cmd", legacy_cmd)
        self.assertNotIn(r"scripts\start_vision2grasp.ps1", legacy_cmd)
        self.assertIn("start_xuanshu_lab.ps1", legacy_script)
        self.assertNotIn("run_vision2grasp_app.py", legacy_script)

        for filename in ("README.md", "README_EN.md", "README_JA.md", "README_KO.md"):
            readme = (PROJECT_ROOT / filename).read_text(encoding="utf-8")
            self.assertIn(r"G:\Vision2Grasp\Start-XUANSHU-LAB.cmd", readme)
            self.assertNotIn("Start-Vision2Grasp.cmd", readme)
            self.assertNotIn(r".\.venv\Scripts\python.exe .\run_vision2grasp_app.py", readme)

    def test_original_intro_and_workspace_routes_remain_the_visible_entry(self) -> None:
        portal = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        moment = (PROJECT_ROOT / "frontend" / "apps" / "moment" / "index.html").read_text(encoding="utf-8")
        gongshu = (PROJECT_ROOT / "frontend" / "apps" / "gongshu" / "index.html").read_text(encoding="utf-8")

        self.assertIn('id="introFrame"', portal)
        self.assertIn('src="./assets/intro/intro.html"', portal)
        self.assertIn('href="./apps/moment/index.html"', portal)
        self.assertIn('href="./apps/gongshu/index.html"', portal)
        self.assertIn('href="../../index.html" aria-label="返回玄枢主页"', moment)
        self.assertIn('href="../../index.html" title="返回玄枢门户"', gongshu)

    def test_launcher_enables_existing_xiezhi_runtime(self) -> None:
        launcher = (PROJECT_ROOT / "scripts" / "start_xuanshu_lab.ps1").read_text(
            encoding="utf-8-sig"
        )
        config = (PROJECT_ROOT / "configs" / "default.toml").read_text(encoding="utf-8")
        self.assertIn('$env:XIEZHI_ENABLED = "1"', launcher)
        self.assertIn("XiezhiLifecycleRuntime", launcher)
        self.assertNotIn("default_algorithm_registry", launcher)
        self.assertIn('[gongshu_xiezhi]\nenabled = true', config)

    def test_gongshu_page_displays_live_xiezhi_lifecycle_status(self) -> None:
        html = (PROJECT_ROOT / "frontend" / "apps" / "gongshu" / "index.html").read_text(
            encoding="utf-8"
        )
        script = (
            PROJECT_ROOT / "frontend" / "apps" / "gongshu" / "xiezhi-lab.js"
        ).read_text(encoding="utf-8")
        for element_id in (
            "xiezhiRuntimeStatus",
            "xiezhiConnectionStatus",
            "xiezhiRuntimeContext",
            "xiezhiLatestEvent",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('fetch("/api/xiezhi/status"', script)


if __name__ == "__main__":
    unittest.main()
