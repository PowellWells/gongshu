"""Lifecycle management for the local XUANSHU runtime service."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import IO
from urllib.error import URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class ServiceHealth:
    ready: bool
    message: str


class LocalServiceController:
    def __init__(self, project_root: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.project_root = project_root.resolve()
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self._process: subprocess.Popen[str] | None = None
        self._stdout_handle: IO[str] | None = None
        self._stderr_handle: IO[str] | None = None

    @property
    def owns_process(self) -> bool:
        return self._process is not None

    def health(self, *, timeout: float = 0.6) -> ServiceHealth:
        request = Request(f"{self.base_url}/api/health", headers={"Cache-Control": "no-cache"})
        try:
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    return ServiceHealth(False, f"HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, ValueError) as error:
            return ServiceHealth(False, str(error))
        ready = (
            payload.get("schema_version") == "vision2grasp.app-health/v1"
            and payload.get("status") == "ok"
        )
        return ServiceHealth(ready, "本地服务已连接" if ready else "服务响应不兼容")

    def start(self, *, timeout: float = 18.0) -> ServiceHealth:
        current = self.health()
        if current.ready:
            return current
        if self._port_is_open():
            raise RuntimeError(f"端口 {self.port} 已被其他程序占用，无法启动 XUANSHU 本地服务。")

        entry = self.project_root / "run_vision2grasp_app.py"
        if not entry.is_file():
            raise RuntimeError(f"本地服务入口不存在：{entry}")
        log_root = self.project_root / "artifacts" / "xuanshu_lab"
        log_root.mkdir(parents=True, exist_ok=True)
        self._stdout_handle = (log_root / "service.stdout.log").open("w", encoding="utf-8")
        self._stderr_handle = (log_root / "service.stderr.log").open("w", encoding="utf-8")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(self.project_root / "src")
        self._process = subprocess.Popen(
            [
                sys.executable,
                str(entry),
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--no-browser",
            ],
            cwd=self.project_root,
            env=environment,
            stdout=self._stdout_handle,
            stderr=self._stderr_handle,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                self._close_logs()
                self._process = None
                raise RuntimeError("XUANSHU 本地服务在就绪前退出，请查看 artifacts/xuanshu_lab 日志。")
            health = self.health()
            if health.ready:
                return health
            time.sleep(0.2)
        self.stop()
        raise RuntimeError("XUANSHU 本地服务启动超时。")

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._close_logs()

    def _port_is_open(self) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(0.25)
            return client.connect_ex((self.host, self.port)) == 0

    def _close_logs(self) -> None:
        for handle_name in ("_stdout_handle", "_stderr_handle"):
            handle = getattr(self, handle_name)
            if handle is not None:
                handle.close()
                setattr(self, handle_name, None)
