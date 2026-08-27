"""Small native utilities used by the HTML-first desktop host."""

from __future__ import annotations

from urllib.parse import urlparse

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import QPlainTextEdit


class LocalWorkspacePage(QWebEnginePage):
    """Keep local workspace navigation embedded and open external links safely."""

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


class LogView(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("logView")
        self.setReadOnly(True)
        self.setMaximumBlockCount(1000)
