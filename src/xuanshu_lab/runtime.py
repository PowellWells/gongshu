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


class LocalVLMController:
    """Own the optional local llama.cpp multimodal service for one desktop run."""

    def __init__(self, project_root: Path, *, host: str = "127.0.0.1", port: int = 8787) -> None:
        self.project_root = project_root.resolve()
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self._process: subprocess.Popen[str] | None = None
        self._stdout_handle: IO[str] | None = None
        self._stderr_handle: IO[str] | None = None

    @property
    def model_path(self) -> Path:
        return Path(os.environ.get(
            "VISION2GRASP_VLM_MODEL",
            str(self.project_root / "artifacts" / "models" / "qwen3-vl-4b-instruct-gguf" / "Qwen3VL-4B-Instruct-Q4_K_M.gguf"),
        ))

    @property
    def mmproj_path(self) -> Path:
        return Path(os.environ.get(
            "VISION2GRASP_VLM_MMPROJ",
            str(self.project_root / "artifacts" / "models" / "qwen3-vl-4b-instruct-gguf" / "mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"),
        ))

    @property
    def executable_path(self) -> Path:
        return Path(os.environ.get(
            "VISION2GRASP_LLAMACPP_SERVER",
            str(self.project_root / "artifacts" / "llama.cpp" / "b11424" / "llama-server.exe"),
        ))

    @property
    def owns_process(self) -> bool:
        return self._process is not None

    def health(self, *, timeout: float = 0.6) -> ServiceHealth:
        request = Request(f"{self.base_url}/health", headers={"Cache-Control": "no-cache"})
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, ValueError) as error:
            return ServiceHealth(False, str(error))
        status = str(payload.get("status", "")).lower()
        return ServiceHealth(status == "ok", "本地 VLM 已就绪" if status == "ok" else f"VLM status={status or 'unknown'}")

    def start(self, *, timeout: float = 180.0) -> ServiceHealth:
        current = self.health()
        if current.ready:
            return current
        asset_specs = (
            (self.executable_path, 1),
            (self.model_path, 2_497_281_664),
            (self.mmproj_path, 453_974_304),
        )
        missing = [
            path for path, minimum_size in asset_specs
            if not path.is_file() or path.stat().st_size < minimum_size
        ]
        if missing:
            return ServiceHealth(False, "本地 VLM 资产未就绪：" + ", ".join(str(path) for path in missing))
        log_root = self.project_root / "artifacts" / "xuanshu_lab"
        log_root.mkdir(parents=True, exist_ok=True)
        self._stdout_handle = (log_root / "vlm.stdout.log").open("w", encoding="utf-8")
        self._stderr_handle = (log_root / "vlm.stderr.log").open("w", encoding="utf-8")
        command = [
            str(self.executable_path),
            "--host", self.host,
            "--port", str(self.port),
            "-m", str(self.model_path),
            "--mmproj", str(self.mmproj_path),
            "--ctx-size", "4096",
            "--n-gpu-layers", "99",
            "--parallel", "1",
            "--image-min-tokens", "1024",
        ]
        self._process = subprocess.Popen(
            command,
            cwd=self.project_root,
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
                return ServiceHealth(False, "本地 VLM 在就绪前退出，请查看 artifacts/xuanshu_lab/vlm.stderr.log")
            health = self.health()
            if health.ready:
                return health
            time.sleep(0.5)
        self.stop()
        return ServiceHealth(False, "本地 VLM 启动超时，请查看 artifacts/xuanshu_lab/vlm.stderr.log")

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._close_logs()

    def _close_logs(self) -> None:
        for handle_name in ("_stdout_handle", "_stderr_handle"):
            handle = getattr(self, handle_name)
            if handle is not None:
                handle.close()
                setattr(self, handle_name, None)


def _service_environment(
    project_root: Path,
    inherited: dict[str, str] | None = None,
) -> dict[str, str]:
    """Prepend Gongshu source while retaining launcher-provided Xiezhi paths."""
    environment = dict(os.environ if inherited is None else inherited)
    inherited_pythonpath = environment.get("PYTHONPATH", "")
    pythonpath_entries = [str(project_root.resolve() / "src")]
    if inherited_pythonpath:
        pythonpath_entries.append(inherited_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    return environment


class LocalServiceController:
    def __init__(self, project_root: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.project_root = project_root.resolve()
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self._process: subprocess.Popen[str] | None = None
        self._stdout_handle: IO[str] | None = None
        self._stderr_handle: IO[str] | None = None
        self.vlm = LocalVLMController(project_root)

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
            and "camera.phone-lan/v1" in payload.get("capabilities", [])
        )
        return ServiceHealth(ready, "本地服务已连接" if ready else "服务响应不兼容")

    def start(self, *, timeout: float = 18.0) -> ServiceHealth:
        current = self.health()
        if current.ready:
            return current
        if self._port_is_open():
            raise RuntimeError(f"端口 {self.port} 已被其他程序占用，无法启动 XUANSHU 本地服务。")

        vlm_health = self.vlm.start()
        if not vlm_health.ready and os.environ.get("VISION2GRASP_VLM_REQUIRED", "0") == "1":
            raise RuntimeError(vlm_health.message)
        if vlm_health.ready:
            os.environ["VISION2GRASP_VLM_URL"] = self.vlm.base_url

        entry = self.project_root / "run_vision2grasp_app.py"
        if not entry.is_file():
            raise RuntimeError(f"本地服务入口不存在：{entry}")
        log_root = self.project_root / "artifacts" / "xuanshu_lab"
        log_root.mkdir(parents=True, exist_ok=True)
        self._stdout_handle = (log_root / "service.stdout.log").open("w", encoding="utf-8")
        self._stderr_handle = (log_root / "service.stderr.log").open("w", encoding="utf-8")
        environment = _service_environment(self.project_root)
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
                self.vlm.stop()
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
        self.vlm.stop()

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
