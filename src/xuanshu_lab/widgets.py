"""Reusable PySide6 widgets for XUANSHU LAB."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .contracts import WorkspaceSpec, WorkspaceStatus


def _label(text: str, object_name: str, *, word_wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(object_name)
    widget.setWordWrap(word_wrap)
    return widget


def _load_icon(path: Path, size: int) -> QLabel:
    label = QLabel()
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pixmap = QPixmap(str(path))
    if not pixmap.isNull():
        label.setPixmap(
            pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    return label


class ClickableCard(QFrame):
    clicked = Signal(str)

    def __init__(self, workspace: WorkspaceSpec, project_root: Path) -> None:
        super().__init__()
        self.workspace = workspace
        self.setObjectName("workspaceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(214)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"打开 {workspace.english_name}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(9)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(_load_icon(project_root / workspace.icon_relative_path, 46))
        title_column = QVBoxLayout()
        title_column.setSpacing(2)
        category = _label(workspace.category, "cardCategory")
        category.setStyleSheet(f"color: {workspace.accent};")
        title_column.addWidget(category)
        title_column.addWidget(_label(workspace.name, "cardName"))
        title_column.addWidget(_label(workspace.english_name, "cardEnglish"))
        top.addLayout(title_column, 1)
        if workspace.status is WorkspaceStatus.PREVIEW:
            top.addWidget(_label("PREVIEW", "previewBadge"), 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        layout.addWidget(_label(workspace.description, "cardDescription", word_wrap=True))
        layout.addStretch(1)
        tags = QHBoxLayout()
        tags.setSpacing(6)
        for capability in workspace.capabilities:
            tags.addWidget(_label(capability, "capabilityTag"))
        tags.addStretch(1)
        arrow = _label("进入工作空间  →", "cardEnglish")
        arrow.setStyleSheet(f"color: {workspace.accent}; font-weight: 750;")
        tags.addWidget(arrow)
        layout.addLayout(tags)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.workspace.workspace_id)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.workspace.workspace_id)
            event.accept()
            return
        super().keyPressEvent(event)


class OverviewPage(QScrollArea):
    workspace_requested = Signal(str)

    def __init__(self, workspaces: tuple[WorkspaceSpec, ...], project_root: Path) -> None:
        super().__init__()
        self.setObjectName("overviewScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("overviewPage")
        self.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 25, 28, 30)
        root.setSpacing(24)

        hero = QFrame()
        hero.setObjectName("heroPanel")
        hero.setMinimumHeight(238)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(30, 27, 30, 27)
        hero_layout.setSpacing(28)
        copy = QVBoxLayout()
        copy.setSpacing(8)
        copy.addWidget(_label("WINDOWS AI / ROBOTICS RESEARCH PLATFORM · V0.1", "heroKicker"))
        title_row = QHBoxLayout()
        title_row.setSpacing(9)
        title_row.addWidget(_label("Welcome to", "heroTitle"))
        title_row.addWidget(_label("XUANSHU LAB", "heroTitleAccent"))
        title_row.addStretch(1)
        copy.addLayout(title_row)
        copy.addWidget(
            _label(
                "把视觉感知、机器人操作与世界模型放进统一、可追踪、可扩展的本地科研桌面。\n当前版本专注稳定的软件骨架，算法能力按 Workspace 独立演进。",
                "heroCopy",
                word_wrap=True,
            )
        )
        copy.addStretch(1)
        copy.addWidget(_label("LOCAL FIRST  ·  MODULAR  ·  TRACEABLE", "heroKicker"))
        hero_layout.addLayout(copy, 1)

        metrics = QHBoxLayout()
        metrics.setSpacing(24)
        for number, caption in (("03", "WORKSPACES"), ("02", "RUNNABLE"), ("01", "PREVIEW")):
            column = QVBoxLayout()
            column.setSpacing(2)
            column.addWidget(_label(number, "metricNumber"), 0, Qt.AlignmentFlag.AlignCenter)
            column.addWidget(_label(caption, "metricLabel"), 0, Qt.AlignmentFlag.AlignCenter)
            metrics.addLayout(column)
        hero_layout.addLayout(metrics)
        root.addWidget(hero)

        section = QHBoxLayout()
        headings = QVBoxLayout()
        headings.setSpacing(3)
        headings.addWidget(_label("Research Workspaces", "sectionTitle"))
        headings.addWidget(_label("选择一个独立研究域；桌面 Shell 统一管理服务、导航和运行状态。", "sectionCopy"))
        section.addLayout(headings)
        section.addStretch(1)
        root.addLayout(section)

        cards = QHBoxLayout()
        cards.setSpacing(16)
        for workspace in workspaces:
            card = ClickableCard(workspace, project_root)
            card.clicked.connect(self.workspace_requested)
            cards.addWidget(card, 1)
        root.addLayout(cards)
        root.addStretch(1)


class LocalWorkspacePage(QWebEnginePage):
    def __init__(self, base_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        parsed = urlparse(base_url)
        self._allowed_host = parsed.hostname
        self._allowed_port = parsed.port

    def acceptNavigationRequest(self, url: QUrl, navigation_type, is_main_frame: bool) -> bool:  # type: ignore[no-untyped-def]
        if url.scheme() in {"about", "data", "blob"}:
            return True
        if url.scheme() in {"http", "https"} and url.host() == self._allowed_host:
            if self._allowed_port is None or url.port() == self._allowed_port:
                return True
        if is_main_frame:
            QDesktopServices.openUrl(url)
            return False
        return False


class WebWorkspacePage(QWidget):
    load_state_changed = Signal(bool, str)

    def __init__(self, workspace: WorkspaceSpec, base_url: str) -> None:
        super().__init__()
        self.workspace = workspace
        self.base_url = base_url.rstrip("/")
        self.route = workspace.route or "/"
        self._loaded_once = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 18)
        outer.setSpacing(0)
        container = QFrame()
        container.setObjectName("webContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(1, 1, 1, 1)
        container_layout.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName("webToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 7, 10, 7)
        toolbar_layout.setSpacing(7)
        self.back_button = QPushButton("←")
        self.back_button.setObjectName("toolButton")
        self.back_button.setFixedWidth(38)
        self.back_button.clicked.connect(self._back)
        self.reload_button = QPushButton("重新载入")
        self.reload_button.setObjectName("toolButton")
        self.reload_button.clicked.connect(self.reload)
        self.address = _label(f"LOCAL  {self.base_url}{self.route}", "webAddress")
        self.address.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        toolbar_layout.addWidget(self.back_button)
        toolbar_layout.addWidget(self.reload_button)
        toolbar_layout.addWidget(self.address, 1)
        container_layout.addWidget(toolbar)

        self.web_view = QWebEngineView()
        self.web_view.setPage(LocalWorkspacePage(self.base_url, self.web_view))
        self.web_view.loadStarted.connect(lambda: self.load_state_changed.emit(False, "正在载入工作空间"))
        self.web_view.loadFinished.connect(self._finished)
        self.web_view.urlChanged.connect(lambda url: self.address.setText(f"LOCAL  {url.toString()}"))
        container_layout.addWidget(self.web_view, 1)
        outer.addWidget(container, 1)

    def ensure_loaded(self) -> None:
        if not self._loaded_once:
            self._loaded_once = True
            self.web_view.setUrl(QUrl(f"{self.base_url}{self.route}"))

    def reload(self) -> None:
        self.ensure_loaded()
        self.web_view.reload()

    def _back(self) -> None:
        if self.web_view.history().canGoBack():
            self.web_view.back()
        else:
            self.web_view.setUrl(QUrl(f"{self.base_url}{self.route}"))

    def _finished(self, success: bool) -> None:
        self.load_state_changed.emit(success, "工作空间已就绪" if success else "工作空间载入失败")


class HetuPreviewPage(QScrollArea):
    def __init__(self, workspace: WorkspaceSpec, project_root: Path) -> None:
        super().__init__()
        self.setObjectName("previewScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("previewPage")
        self.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 24, 28, 32)
        root.setSpacing(22)

        hero = QFrame()
        hero.setObjectName("previewHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(30, 28, 30, 28)
        hero_layout.setSpacing(26)
        hero_layout.addWidget(_load_icon(project_root / workspace.icon_relative_path, 92))
        copy = QVBoxLayout()
        copy.setSpacing(8)
        copy.addWidget(_label("WORLD MODEL RESEARCH WORKSPACE · PREVIEW", "heroKicker"))
        title = QHBoxLayout()
        title.addWidget(_label("河图", "previewTitle"))
        title.addWidget(_label("Hetu", "previewAccent"))
        title.addStretch(1)
        copy.addLayout(title)
        copy.addWidget(
            _label(
                "河图将承载环境状态表征、时序预测和仿真桥接。本页是软件骨架预告，不运行未完成的世界模型，也不展示虚假指标。",
                "heroCopy",
                word_wrap=True,
            )
        )
        copy.addWidget(_label("PREVIEW ONLY · NO MODEL EXECUTION", "previewBadge"), 0, Qt.AlignmentFlag.AlignLeft)
        hero_layout.addLayout(copy, 1)
        root.addWidget(hero)

        root.addWidget(_label("Planned Capability Modules", "sectionTitle"))
        concepts = QHBoxLayout()
        concepts.setSpacing(14)
        concept_data = (
            ("01", "Spatial State", "统一表达场景实体、空间关系与可操作区域。"),
            ("02", "Temporal Forecast", "追踪状态变化，为下一步动作提供可验证预测。"),
            ("03", "Simulation Bridge", "连接真实观察与仿真环境，记录假设和验证结果。"),
        )
        for index, title, description in concept_data:
            card = QFrame()
            card.setObjectName("conceptCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(18, 17, 18, 17)
            layout.setSpacing(7)
            layout.addWidget(_label(index, "conceptIndex"))
            layout.addWidget(_label(title, "conceptTitle"))
            layout.addWidget(_label(description, "conceptCopy", word_wrap=True))
            layout.addStretch(1)
            concepts.addWidget(card, 1)
        root.addLayout(concepts)

        root.addWidget(_label("v0.1 → Future", "sectionTitle"))
        roadmap = QFrame()
        roadmap.setObjectName("roadmapRow")
        roadmap_layout = QHBoxLayout(roadmap)
        roadmap_layout.setContentsMargins(20, 16, 20, 16)
        roadmap_layout.setSpacing(16)
        for stage, text in (
            ("SKELETON", "Workspace 注册、导航与状态边界"),
            ("DATA", "统一场景数据契约与回放"),
            ("MODEL", "可替换的预测模型适配器"),
            ("VALIDATE", "真实观察与仿真结果对照"),
        ):
            column = QVBoxLayout()
            column.addWidget(_label(stage, "conceptIndex"))
            column.addWidget(_label(text, "roadmapCopy", word_wrap=True))
            roadmap_layout.addLayout(column, 1)
        root.addWidget(roadmap)
        root.addStretch(1)


class LogView(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("logView")
        self.setReadOnly(True)
        self.setMaximumBlockCount(1000)
