"""Native window and runtime utilities for the HTML-first XUANSHU LAB desktop."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QTextCursor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QDockWidget, QMainWindow

from .registry import WorkspaceRegistry
from .runtime import LocalServiceController
from .widgets import LocalWorkspacePage, LogView


class MainWindow(QMainWindow):
    """A thin Windows host that leaves all visible product UI to the web app."""

    activation_requested = Signal()

    def __init__(
        self,
        project_root: Path,
        registry: WorkspaceRegistry,
        service: LocalServiceController,
        *,
        settings: QSettings | None = None,
    ) -> None:
        super().__init__()
        self.project_root = project_root
        self.registry = registry
        self.service = service
        self.settings = settings or QSettings("XUANSHU", "XUANSHU LAB")
        self.portal_url = f"{self.service.base_url.rstrip('/')}/index.html"
        self.service_ready = False

        self.setWindowTitle("XUANSHU LAB · 玄枢 AI")
        icon_path = project_root / "frontend" / "apps" / "portal" / "assets" / "xuanshu-orbit.png"
        self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1460, 900)
        self.setMinimumSize(1120, 720)

        self.web_view = QWebEngineView(self)
        self.web_view.setObjectName("xuanshuPortal")
        self.web_view.setPage(LocalWorkspacePage(self.service.base_url, self.web_view))
        self.web_view.titleChanged.connect(self._update_window_title)
        self.setCentralWidget(self.web_view)

        self._build_logs()
        self._build_shortcuts()
        self._restore_geometry()
        self.go_home()

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(3000)
        self._health_timer.timeout.connect(self._refresh_health)
        self._health_timer.start()
        self._refresh_health()
        self.activation_requested.connect(self.bring_to_front)

    def _build_shortcuts(self) -> None:
        self.home_action = QAction("返回玄枢主页", self)
        self.home_action.setShortcut(QKeySequence("Alt+Home"))
        self.home_action.triggered.connect(self.go_home)

        self.reload_action = QAction("刷新当前页面", self)
        self.reload_action.setShortcuts((QKeySequence.Refresh, QKeySequence("Ctrl+R")))
        self.reload_action.triggered.connect(self.web_view.reload)

        self.logs_action = QAction("显示运行日志", self)
        self.logs_action.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.logs_action.triggered.connect(self.toggle_logs)

        for action in (self.home_action, self.reload_action, self.logs_action):
            self.addAction(action)

    def _build_logs(self) -> None:
        self.log_dock = QDockWidget("XUANSHU RUNTIME LOG · Ctrl+Shift+L", self)
        self.log_dock.setObjectName("runtimeLogDock")
        self.log_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.log_view = LogView()
        self.log_dock.setWidget(self.log_view)
        self.log_dock.setMinimumHeight(150)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

    def go_home(self) -> None:
        """Return to the original portal; its own HTML controls the intro animation."""
        self.web_view.setUrl(QUrl(self.portal_url))

    def toggle_logs(self) -> None:
        if self.log_dock.isVisible():
            self.log_dock.hide()
            return
        self._load_logs()
        self.log_dock.show()
        self.log_dock.raise_()

    def _load_logs(self) -> None:
        log_root = self.project_root / "artifacts" / "xuanshu_lab"
        sections: list[str] = []
        for filename in ("service.stdout.log", "service.stderr.log"):
            path = log_root / filename
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")[-24000:]
                sections.append(f"--- {filename} ---\n{content.strip()}")
        self.log_view.setPlainText("\n\n".join(sections) or "本次会话尚无服务日志。")
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def _refresh_health(self) -> None:
        self.service_ready = self.service.health(timeout=0.4).ready

    def _update_window_title(self, page_title: str) -> None:
        title = page_title.strip()
        self.setWindowTitle(f"{title} · XUANSHU LAB" if title else "XUANSHU LAB · 玄枢 AI")

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _restore_geometry(self) -> None:
        geometry = self.settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("window_geometry", self.saveGeometry())
        self._health_timer.stop()
        self.service.stop()
        super().closeEvent(event)
