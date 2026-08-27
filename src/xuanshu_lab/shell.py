"""Main XUANSHU LAB desktop window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .contracts import WorkspaceKind, WorkspaceSpec, WorkspaceStatus
from .registry import WorkspaceRegistry
from .runtime import LocalServiceController
from .widgets import HetuPreviewPage, LogView, OverviewPage, WebWorkspacePage


class NavButton(QPushButton):
    def __init__(self, text: str, page_id: str) -> None:
        super().__init__(text)
        self.page_id = page_id
        self.setObjectName("navButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class AboutDialog(QDialog):
    def __init__(self, project_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("关于 XUANSHU LAB")
        self.setModal(True)
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(10)
        kicker = QLabel("WINDOWS AI / ROBOTICS RESEARCH PLATFORM")
        kicker.setObjectName("pageEyebrow")
        title = QLabel("XUANSHU LAB  v0.1")
        title.setObjectName("pageTitle")
        copy = QLabel(
            "本地优先的 AI 与机器人科研桌面平台。\n\n"
            "PySide6 负责桌面外壳、Workspace 生命周期和运行状态；"
            "现有 Web 工作台作为可替换 Workspace 嵌入。\n\n"
            f"项目目录：{project_root}"
        )
        copy.setObjectName("pageSubtitle")
        copy.setWordWrap(True)
        copy.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        close_button = QPushButton("关闭")
        close_button.setObjectName("primaryButton")
        close_button.clicked.connect(self.accept)
        layout.addWidget(kicker)
        layout.addWidget(title)
        layout.addWidget(copy)
        layout.addSpacing(8)
        layout.addWidget(close_button)


class MainWindow(QMainWindow):
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
        self._pages: dict[str, QWidget] = {}
        self._page_indexes: dict[str, int] = {}
        self._nav_buttons: dict[str, NavButton] = {}

        self.setWindowTitle("XUANSHU LAB · AI / Robotics Research Platform")
        icon_path = project_root / "frontend" / "apps" / "portal" / "assets" / "xuanshu-orbit.png"
        self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1460, 900)
        self.setMinimumSize(1120, 720)
        self._build_shell(icon_path)
        self._build_logs()
        self._build_status_bar()
        self._restore_state()

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(3000)
        self._health_timer.timeout.connect(self._refresh_health)
        self._health_timer.start()
        self._refresh_health()
        self.activation_requested.connect(self.bring_to_front)

    def _build_shell(self, icon_path: Path) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._create_side_rail(icon_path))

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._create_top_bar())

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("contentStack")
        overview = OverviewPage(tuple(self.registry), self.project_root)
        overview.workspace_requested.connect(self.show_page)
        self._add_page("overview", overview)
        for workspace in self.registry:
            if workspace.kind is WorkspaceKind.WEB:
                page = WebWorkspacePage(workspace, self.service.base_url)
                page.load_state_changed.connect(self._workspace_load_state)
            else:
                page = HetuPreviewPage(workspace, self.project_root)
            self._add_page(workspace.workspace_id, page)
        main_layout.addWidget(self.content_stack, 1)
        shell.addWidget(main, 1)

    def _create_side_rail(self, icon_path: Path) -> QFrame:
        rail = QFrame()
        rail.setObjectName("sideRail")
        rail.setFixedWidth(246)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(16, 19, 16, 17)
        layout.setSpacing(5)

        brand = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(48, 48)
        pixmap = QPixmap(str(icon_path))
        if not pixmap.isNull():
            logo.setPixmap(
                pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        brand_copy = QVBoxLayout()
        brand_copy.setSpacing(1)
        chinese = QLabel("玄枢实验室")
        chinese.setObjectName("brandChinese")
        english = QLabel("XUANSHU LAB")
        english.setObjectName("brandEnglish")
        brand_copy.addWidget(chinese)
        brand_copy.addWidget(english)
        brand.addWidget(logo)
        brand.addLayout(brand_copy)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(18)

        section = QLabel("PLATFORM")
        section.setObjectName("railSection")
        layout.addWidget(section)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._add_nav_button(layout, "◇  研究总览", "overview")

        workspaces = QLabel("WORKSPACES")
        workspaces.setObjectName("railSection")
        layout.addWidget(workspaces)
        for workspace in self.registry:
            prefix = "●" if workspace.status is WorkspaceStatus.READY else "◌"
            self._add_nav_button(layout, f"{prefix}  {workspace.name}  {workspace.english_name.split()[0]}", workspace.workspace_id)

        layout.addStretch(1)
        runtime = QFrame()
        runtime.setObjectName("railRuntime")
        runtime_layout = QVBoxLayout(runtime)
        runtime_layout.setContentsMargins(12, 11, 12, 11)
        runtime_layout.setSpacing(4)
        version = QLabel("PLATFORM  v0.1")
        version.setObjectName("railRuntimeTitle")
        copy = QLabel("LOCAL · PRIVATE · MODULAR")
        copy.setObjectName("railRuntimeCopy")
        self.rail_service = QLabel("●  Runtime checking")
        self.rail_service.setObjectName("railRuntimeCopy")
        runtime_layout.addWidget(version)
        runtime_layout.addWidget(copy)
        runtime_layout.addSpacing(4)
        runtime_layout.addWidget(self.rail_service)
        layout.addWidget(runtime)
        return rail

    def _add_nav_button(self, layout: QVBoxLayout, text: str, page_id: str) -> None:
        button = NavButton(text, page_id)
        button.clicked.connect(lambda _checked=False, target=page_id: self.show_page(target))
        self.nav_group.addButton(button)
        self._nav_buttons[page_id] = button
        layout.addWidget(button)

    def _create_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(78)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 11, 20, 11)
        layout.setSpacing(12)
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        self.page_eyebrow = QLabel("PLATFORM OVERVIEW")
        self.page_eyebrow.setObjectName("pageEyebrow")
        self.page_title = QLabel("研究总览")
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("统一管理本地 AI 与机器人科研工作空间")
        self.page_subtitle.setObjectName("pageSubtitle")
        title_column.addWidget(self.page_eyebrow)
        title_column.addWidget(self.page_title)
        title_column.addWidget(self.page_subtitle)
        layout.addLayout(title_column)
        layout.addStretch(1)
        self.service_pill = QLabel("●  CHECKING")
        self.service_pill.setObjectName("statusPillWaiting")
        layout.addWidget(self.service_pill)

        self.home_button = QPushButton("总览")
        self.home_button.setObjectName("toolButton")
        self.home_button.clicked.connect(lambda: self.show_page("overview"))
        self.reload_button = QPushButton("刷新")
        self.reload_button.setObjectName("toolButton")
        self.reload_button.clicked.connect(self.reload_current_page)
        self.log_button = QPushButton("运行日志")
        self.log_button.setObjectName("toolButton")
        self.log_button.clicked.connect(self.toggle_logs)
        self.about_button = QPushButton("关于")
        self.about_button.setObjectName("toolButton")
        self.about_button.clicked.connect(lambda: AboutDialog(self.project_root, self).exec())
        for button in (self.home_button, self.reload_button, self.log_button, self.about_button):
            layout.addWidget(button)
        return bar

    def _add_page(self, page_id: str, page: QWidget) -> None:
        self._pages[page_id] = page
        self._page_indexes[page_id] = self.content_stack.addWidget(page)

    def _build_logs(self) -> None:
        self.log_dock = QDockWidget("XUANSHU RUNTIME LOG", self)
        self.log_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.log_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.log_view = LogView()
        self.log_dock.setWidget(self.log_view)
        self.log_dock.setMinimumHeight(150)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

    def _build_status_bar(self) -> None:
        status = QStatusBar()
        status.setSizeGripEnabled(False)
        status.showMessage("XUANSHU LAB v0.1 · 本地科研模式")
        self.status_runtime = QLabel("Runtime: checking")
        status.addPermanentWidget(self.status_runtime)
        self.setStatusBar(status)

    def show_page(self, page_id: str) -> None:
        if page_id not in self._pages:
            raise KeyError(f"unknown page: {page_id}")
        self.content_stack.setCurrentIndex(self._page_indexes[page_id])
        self._nav_buttons[page_id].setChecked(True)
        self.settings.setValue("last_workspace", page_id)
        if page_id == "overview":
            self.page_eyebrow.setText("PLATFORM OVERVIEW")
            self.page_title.setText("研究总览")
            self.page_subtitle.setText("统一管理本地 AI 与机器人科研工作空间")
            self.reload_button.setEnabled(False)
            return
        workspace = self.registry.get(page_id)
        self.page_eyebrow.setText(workspace.category)
        self.page_title.setText(f"{workspace.name} · {workspace.english_name}")
        self.page_subtitle.setText(workspace.description)
        self.reload_button.setEnabled(workspace.kind is WorkspaceKind.WEB)
        page = self._pages[page_id]
        if isinstance(page, WebWorkspacePage):
            page.ensure_loaded()

    def reload_current_page(self) -> None:
        page = self.content_stack.currentWidget()
        if isinstance(page, WebWorkspacePage):
            page.reload()

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
        health = self.service.health(timeout=0.4)
        if health.ready:
            self.service_pill.setText("●  LOCAL RUNTIME READY")
            self.service_pill.setObjectName("statusPillReady")
            self.rail_service.setText("●  Runtime connected")
            self.rail_service.setStyleSheet("color: #58D4B8;")
            self.status_runtime.setText("Runtime: 127.0.0.1:8765 · READY")
        else:
            self.service_pill.setText("●  RUNTIME OFFLINE")
            self.service_pill.setObjectName("statusPillWaiting")
            self.rail_service.setText("●  Runtime offline")
            self.rail_service.setStyleSheet("color: #E2B66D;")
            self.status_runtime.setText("Runtime: OFFLINE")
        self.service_pill.style().unpolish(self.service_pill)
        self.service_pill.style().polish(self.service_pill)

    def _workspace_load_state(self, success: bool, message: str) -> None:
        self.statusBar().showMessage(message, 3500)
        if not success and "正在" not in message:
            self._load_logs()

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _restore_state(self) -> None:
        geometry = self.settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        last_page = str(self.settings.value("last_workspace", "overview"))
        if last_page not in self._pages:
            last_page = "overview"
        self.show_page(last_page)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings.setValue("window_geometry", self.saveGeometry())
        self._health_timer.stop()
        self.service.stop()
        super().closeEvent(event)
