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

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from xuanshu_lab.contracts import WorkspaceKind, WorkspaceSpec, WorkspaceStatus
from xuanshu_lab.registry import WorkspaceRegistry, create_default_registry
from xuanshu_lab.runtime import LocalServiceController, ServiceHealth
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
            {"schema_version": "vision2grasp.app-health/v1", "status": "ok"}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class LocalServiceControllerTests(unittest.TestCase):
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

    def test_shell_exposes_overview_and_three_registered_pages(self) -> None:
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
                self.assertEqual(window.content_stack.count(), 4)
                self.assertEqual(set(window._pages), {"overview", "moment", "gongshu", "hetu"})
                window.show_page("hetu")
                self.assertIn("Hetu", window.page_title.text())
                self.assertFalse(window.reload_button.isEnabled())
                window.show_page("moment")
                self.assertTrue(window.reload_button.isEnabled())
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
