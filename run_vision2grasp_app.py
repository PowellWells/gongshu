"""Serve the unified local app and real-scene perception API."""

from __future__ import annotations

import argparse
import base64
import binascii
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from typing import Any
from urllib.parse import urlparse
import webbrowser

import cv2
import numpy as np

from vision2grasp.perception import UltralyticsSegmenterConfig, UltralyticsYOLOSegmenter
from vision2grasp.real_scene import RealScenePerceptionPipeline
from vision2grasp.real_scene_service import RealSceneProcessor
from vision2grasp.sources import OpenCVCameraConfig, OpenCVCameraSource, RGBArraySource
from vision2grasp.visualization import make_run_id


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
CALIBRATION_PATH = PROJECT_ROOT / "artifacts" / "real_scene" / "table_calibration.json"
RUNTIME_ROOT = FRONTEND_ROOT / "runtime"
RUNTIME_RUNS_ROOT = RUNTIME_ROOT / "runs"
LAUNCHER_LOG_ROOT = PROJECT_ROOT / "artifacts" / "launcher"
MAX_JSON_BODY_BYTES = 20 * 1024 * 1024


class Vision2GraspApp:
    def __init__(self) -> None:
        segmenter = UltralyticsYOLOSegmenter(
            UltralyticsSegmenterConfig(target_class_names=("bottle",))
        )
        self.real_scene = RealSceneProcessor(
            RealScenePerceptionPipeline(segmenter),
            calibration_path=CALIBRATION_PATH,
            target_fps=2.0,
        )
        self._simulation_lock = threading.Lock()

    def start_camera(self, value: int | str) -> None:
        name = f"camera-{value}" if isinstance(value, int) else "android-network-camera"
        source = OpenCVCameraSource(
            OpenCVCameraConfig(source=value, width=640, height=480, camera_name=name)
        )
        self.real_scene.set_source(
            source,
            kind="camera" if isinstance(value, int) else "network_camera",
        )

    def set_uploaded_image(self, rgb: np.ndarray) -> None:
        self.real_scene.set_source(
            RGBArraySource(rgb),
            kind="image",
        )

    def run_simulation(self) -> dict[str, Any]:
        if not self._simulation_lock.acquire(blocking=False):
            raise RuntimeError("a simulation run is already in progress")
        try:
            RUNTIME_RUNS_ROOT.mkdir(parents=True, exist_ok=True)
            LAUNCHER_LOG_ROOT.mkdir(parents=True, exist_ok=True)
            run_id = make_run_id("app-bottle-seed7")
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(PROJECT_ROOT / "run_bottle_pipeline.py"),
                        "--output-root",
                        str(RUNTIME_RUNS_ROOT),
                        "--run-id",
                        run_id,
                    ],
                    cwd=PROJECT_ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("simulation timed out after 120 seconds") from error
            (LAUNCHER_LOG_ROOT / "latest.stdout.log").write_text(
                completed.stdout, encoding="utf-8"
            )
            (LAUNCHER_LOG_ROOT / "latest.stderr.log").write_text(
                completed.stderr, encoding="utf-8"
            )
            run_json_path = RUNTIME_RUNS_ROOT / run_id / "run.json"
            if not run_json_path.is_file():
                raise RuntimeError(
                    "simulation did not produce run.json; see artifacts/launcher logs"
                )
            document = json.loads(run_json_path.read_text(encoding="utf-8"))
            if document.get("schema_version") != "vision2grasp.run/v1":
                raise RuntimeError("simulation produced an unsupported run schema")
            manifest = {
                "schema_version": "vision2grasp.launcher/v1",
                "run_json": f"runs/{run_id}/run.json",
            }
            RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
            temporary = RUNTIME_ROOT / "latest.json.tmp"
            temporary.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(RUNTIME_ROOT / "latest.json")
            return {
                "status": "ok",
                "run_id": run_id,
                "pipeline_status": document.get("status"),
                "isolated_lift_acceptance": (
                    "PASS" if completed.returncode == 0 else "FAIL"
                ),
            }
        finally:
            self._simulation_lock.release()


class AppRequestHandler(SimpleHTTPRequestHandler):
    server_version = "Vision2GraspLocal/1.0"

    def __init__(self, *args: Any, app: Vision2GraspApp, **kwargs: Any) -> None:
        self.app = app
        super().__init__(*args, directory=str(FRONTEND_ROOT), **kwargs)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(
                {
                    "schema_version": "vision2grasp.app-health/v1",
                    "status": "ok",
                }
            )
            return
        if path == "/api/real-scene/state":
            self._send_json(self.app.real_scene.snapshot())
            return
        image_prefix = "/api/real-scene/frame/"
        if path.startswith(image_prefix) and path.endswith(".jpg"):
            kind = path[len(image_prefix) : -4]
            if kind not in {"live", "spatial", "grasp"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            image = self.app.real_scene.image(kind)
            if image is None:
                self.send_error(HTTPStatus.NOT_FOUND, "real frame not ready")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(image)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(image)
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_json_body()
            if path == "/api/real-scene/source":
                self._set_source(body)
                return
            if path == "/api/real-scene/calibration":
                calibration = self.app.real_scene.set_calibration(
                    image_points_px=body["image_points_px"],
                    table_width_m=float(body["table_width_mm"]) / 1000.0,
                    table_height_m=float(body["table_height_mm"]) / 1000.0,
                )
                self._send_json(
                    {
                        "status": "ok",
                        "image_coverage_ratio": calibration.image_coverage_ratio,
                    }
                )
                return
            if path == "/api/simulation/run":
                self._send_json(self.app.run_simulation())
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            self._send_json({"status": "error", "message": str(error)}, status=400)

    def _set_source(self, body: dict[str, Any]) -> None:
        kind = str(body.get("kind", ""))
        if kind == "camera":
            value = body.get("value", 0)
            if not isinstance(value, int):
                raise ValueError("local camera value must be an integer index")
            self.app.start_camera(value)
        elif kind == "url":
            value = str(body.get("value", "")).strip()
            parsed = urlparse(value)
            if parsed.scheme.lower() not in {"http", "https", "rtsp"}:
                raise ValueError("Android stream URL must use http, https, or rtsp")
            self.app.start_camera(value)
        elif kind == "image":
            data_url = str(body.get("data_url", ""))
            if not data_url.startswith("data:image/") or ";base64," not in data_url:
                raise ValueError("uploaded image must be a base64 image data URL")
            try:
                encoded = data_url.split(",", 1)[1]
                binary = base64.b64decode(encoded, validate=True)
            except (binascii.Error, IndexError) as error:
                raise ValueError("uploaded image data is invalid") from error
            if len(binary) > 15 * 1024 * 1024:
                raise ValueError("uploaded image exceeds 15 MB")
            bgr = cv2.imdecode(np.frombuffer(binary, dtype=np.uint8), cv2.IMREAD_COLOR)
            if bgr is None:
                raise ValueError("uploaded image could not be decoded")
            self.app.set_uploaded_image(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        else:
            raise ValueError("source kind must be camera, url, or image")
        self._send_json({"status": "ok"})

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if length <= 0 or length > MAX_JSON_BODY_BYTES:
            raise ValueError("JSON body size is invalid")
        payload = self.rfile.read(length)
        document = json.loads(payload.decode("utf-8"))
        if not isinstance(document, dict):
            raise ValueError("JSON body must be an object")
        return document

    def _send_json(self, document: dict[str, Any], *, status: int = 200) -> None:
        payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


class LocalAppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Vision2Grasp app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--camera", default="0", help="Local camera index or stream URL.")
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def _camera_value(value: str) -> int | str:
    stripped = value.strip()
    return int(stripped) if stripped.isdigit() else stripped


def main() -> int:
    args = _parse_args()
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    app = Vision2GraspApp()
    app.real_scene.start()
    if not args.no_camera:
        try:
            app.start_camera(_camera_value(args.camera))
        except (RuntimeError, ValueError) as error:
            print(f"camera startup warning: {error}")
    handler = partial(AppRequestHandler, app=app)
    server = LocalAppServer((args.host, args.port), handler)
    stop_once = threading.Event()

    def stop_server(*_: Any) -> None:
        if stop_once.is_set():
            return
        stop_once.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop_server)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, stop_server)
    url = f"http://{args.host}:{args.port}/apps/gongshu/index.html"
    print(f"Vision2Grasp app: {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        app.real_scene.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
