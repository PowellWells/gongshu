"""Application bootstrap for XUANSHU LAB."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from .registry import create_default_registry
from .runtime import LocalServiceController
from .shell import MainWindow


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


def main() -> int:
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-features=TranslateUI")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("XUANSHU LAB")
    app.setApplicationDisplayName("XUANSHU LAB")
    app.setOrganizationName("XUANSHU")
    app.setStyle("Fusion")

    guard = SingleInstanceGuard()
    if guard.notify_existing():
        return 0
    try:
        guard.listen()
    except RuntimeError as error:
        QMessageBox.critical(None, "XUANSHU LAB 启动失败", str(error))
        return 1

    service = LocalServiceController(PROJECT_ROOT)
    try:
        service.start()
        window = MainWindow(PROJECT_ROOT, create_default_registry(), service)
        guard.attach_window(window)
    except Exception as error:
        service.stop()
        QMessageBox.critical(None, "XUANSHU LAB 启动失败", str(error))
        return 1

    window.show()
    return app.exec()
