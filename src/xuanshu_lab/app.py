"""Application bootstrap for XUANSHU LAB."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from .registry import create_default_registry
from .runtime import LocalServiceController
from .shell import MainWindow
from .theme import APP_STYLESHEET


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTANCE_NAME = "xuanshu-lab-v0.1-local-instance"


class SingleInstanceGuard:
    def __init__(self) -> None:
        self.server = QLocalServer()
        self.window: MainWindow | None = None

    def notify_existing(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(INSTANCE_NAME)
        if not socket.waitForConnected(250):
            return False
        socket.write(b"activate")
        socket.flush()
        socket.waitForBytesWritten(250)
        socket.disconnectFromServer()
        return True

    def listen(self) -> None:
        QLocalServer.removeServer(INSTANCE_NAME)
        if not self.server.listen(INSTANCE_NAME):
            raise RuntimeError("无法建立 XUANSHU LAB 单实例通道。")

        def handle_connection() -> None:
            connection = self.server.nextPendingConnection()
            if connection is not None:
                connection.waitForReadyRead(100)
                connection.readAll()
                connection.disconnectFromServer()
            if self.window is not None:
                self.window.activation_requested.emit()

        self.server.newConnection.connect(handle_connection)

    def attach_window(self, window: MainWindow) -> None:
        self.window = window


def _create_splash() -> QSplashScreen:
    pixmap = QPixmap(720, 390)
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, 720, 390)
    gradient.setColorAt(0.0, QColor("#061A35"))
    gradient.setColorAt(0.62, QColor("#0A315D"))
    gradient.setColorAt(1.0, QColor("#0D5585"))
    painter.fillRect(pixmap.rect(), gradient)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(72, 160, 248, 80))
    for radius in (80, 125, 170, 215):
        painter.drawEllipse(515 - radius, 195 - radius, radius * 2, radius * 2)
    painter.setPen(QColor("#67B3FF"))
    painter.setFont(QFont("Cascadia Mono", 9, QFont.Weight.DemiBold))
    painter.drawText(52, 74, "WINDOWS AI / ROBOTICS RESEARCH PLATFORM")
    painter.setPen(QColor("#FFFFFF"))
    painter.setFont(QFont("Microsoft YaHei UI", 34, QFont.Weight.Bold))
    painter.drawText(50, 153, "玄枢实验室")
    painter.setPen(QColor("#75B9FF"))
    painter.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
    painter.drawText(51, 201, "XUANSHU LAB")
    painter.setPen(QColor("#A8BED6"))
    painter.setFont(QFont("Microsoft YaHei UI", 11))
    painter.drawText(53, 248, "感知世界 · 理解世界 · 创造世界")
    painter.setPen(QColor("#64DCC3"))
    painter.setFont(QFont("Cascadia Mono", 9, QFont.Weight.DemiBold))
    painter.drawText(53, 324, "LOCAL FIRST  ·  MODULAR  ·  TRACEABLE  ·  v0.1")
    painter.end()
    splash = QSplashScreen(pixmap)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    return splash


def main() -> int:
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-features=TranslateUI")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("XUANSHU LAB")
    app.setApplicationDisplayName("XUANSHU LAB")
    app.setOrganizationName("XUANSHU")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    guard = SingleInstanceGuard()
    if guard.notify_existing():
        return 0
    try:
        guard.listen()
    except RuntimeError as error:
        QMessageBox.critical(None, "XUANSHU LAB 启动失败", str(error))
        return 1

    splash = _create_splash()
    splash.show()
    splash.showMessage(
        "  正在连接本地科研运行时…",
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
        QColor("#DCEBFA"),
    )
    app.processEvents()

    service = LocalServiceController(PROJECT_ROOT)
    try:
        service.start()
        window = MainWindow(PROJECT_ROOT, create_default_registry(), service)
        guard.attach_window(window)
    except Exception as error:
        service.stop()
        splash.close()
        QMessageBox.critical(None, "XUANSHU LAB 启动失败", str(error))
        return 1

    window.show()
    splash.finish(window)
    return app.exec()
