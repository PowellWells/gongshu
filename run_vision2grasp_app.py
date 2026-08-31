"""Serve the unified local app and real-scene perception API."""

from __future__ import annotations

import argparse
import base64
import binascii
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing as mp
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import tomllib
from typing import Any
from urllib.parse import urlparse
import webbrowser

import cv2
import numpy as np

from vision2grasp.camera import PhoneLANConfig, PhoneLANProvider
from vision2grasp.grasp_planning import (
    GeometricGraspPlanner,
    GeometricGraspPlannerConfig,
    GraspPlanningService,
)
from vision2grasp.perception import UltralyticsSegmenterConfig, UltralyticsYOLOSegmenter
from vision2grasp.real_scene import RealScenePerceptionPipeline
from vision2grasp.real_scene_service import RealSceneProcessor
from vision2grasp.sources import OpenCVCameraConfig, OpenCVCameraSource, RGBArraySource
from vision2grasp.spatial_perception import (
    CalibratedCameraIntrinsicsProvider,
    MaskSpatialPerceptionProvider,
    MaskSpatialPerceptionConfig,
    MODEL_REVISION,
    PersistentDepthWorkerProvider,
    UPSTREAM_CODE_REVISION,
    MonocularDepthConfig,
    NominalFOVCameraIntrinsicsProvider,
    NominalFOVIntrinsicsConfig,
    PriorityCameraIntrinsicsProvider,
    SpatialPerceptionProvider,
    SpatialPerceptionService,
    SpatialWatchdogConfig,
)
from vision2grasp.target_perception import FastSAMTargetSegmenter, TargetPerceptionService
from vision2grasp.simulation import MuJoCoValidationService
from vision2grasp.visualization import make_run_id


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
CALIBRATION_PATH = PROJECT_ROOT / "artifacts" / "real_scene" / "table_calibration.json"
RUNTIME_ROOT = FRONTEND_ROOT / "runtime"
RUNTIME_RUNS_ROOT = RUNTIME_ROOT / "runs"
LAUNCHER_LOG_ROOT = PROJECT_ROOT / "artifacts" / "launcher"
MAX_JSON_BODY_BYTES = 20 * 1024 * 1024


def _spatial_perception_config() -> dict[str, Any]:
    with (PROJECT_ROOT / "configs" / "default.toml").open("rb") as stream:
        document = tomllib.load(stream)
    return dict(document["spatial_perception"])


def build_spatial_watchdog(config: dict[str, Any] | None = None) -> SpatialWatchdogConfig:
    values = config or _spatial_perception_config()
    return SpatialWatchdogConfig(
        heartbeat_interval_s=float(values["heartbeat_interval_s"]),
        download_warning_stall_s=float(values["download_warning_stall_s"]),
        download_timeout_stall_s=float(values["download_timeout_stall_s"]),
        checksum_warning_s=float(values["checksum_warning_s"]),
        checksum_timeout_s=float(values["checksum_timeout_s"]),
        model_loading_warning_s=float(values["model_loading_warning_s"]),
        model_loading_timeout_s=float(values["model_loading_timeout_s"]),
        depth_inference_warning_s=float(values["depth_inference_warning_s"]),
        depth_inference_timeout_s=float(values["depth_inference_timeout_s"]),
        point_cloud_warning_s=float(values["point_cloud_warning_s"]),
        point_cloud_timeout_s=float(values["point_cloud_timeout_s"]),
        spatial_computing_warning_s=float(values["spatial_computing_warning_s"]),
        spatial_computing_timeout_s=float(values["spatial_computing_timeout_s"]),
    )


def build_spatial_perception_provider(
    config: dict[str, Any] | None = None,
) -> SpatialPerceptionProvider:
    config = config or _spatial_perception_config()
    if str(config["backend"]) != "depth_anything_v2_metric_indoor_small":
        raise ValueError("unsupported spatial perception backend")
    if str(config["model_revision"]) != MODEL_REVISION:
        raise ValueError("spatial perception model revision does not match frozen backend")
    if str(config["upstream_code_revision"]) != UPSTREAM_CODE_REVISION:
        raise ValueError("spatial perception upstream code revision does not match frozen backend")
    return MaskSpatialPerceptionProvider(
        PersistentDepthWorkerProvider(
            MonocularDepthConfig(
                device=str(config["device"]),
                input_size=int(config["input_size"]),
            ),
            build_spatial_watchdog(config),
        ),
        PriorityCameraIntrinsicsProvider(
            (
                CalibratedCameraIntrinsicsProvider.from_user_config(),
                NominalFOVCameraIntrinsicsProvider(
                    NominalFOVIntrinsicsConfig(
                        nominal_diagonal_fov_deg=float(
                            config["nominal_diagonal_fov_deg"]
                        )
                    )
                ),
            )
        ),
        MaskSpatialPerceptionConfig(
            minimum_valid_depth_ratio=float(config["minimum_valid_depth_ratio"]),
            minimum_points=int(config["minimum_points"]),
            maximum_points=int(config["maximum_points"]),
            outlier_mad_scale=float(config["outlier_mad_scale"]),
            minimum_depth_band=float(config["minimum_depth_band"]),
        ),
    )


def build_grasp_planner() -> GeometricGraspPlanner:
    with (PROJECT_ROOT / "configs" / "default.toml").open("rb") as stream:
        config = tomllib.load(stream)["gongshu_grasp_planning"]
    if str(config["strategy"]) != "geometric_pca_top_down":
        raise ValueError("unsupported Gongshu grasp planning strategy")
    return GeometricGraspPlanner(
        GeometricGraspPlannerConfig(
            minimum_points=int(config["minimum_points"]),
            extent_lower_quantile=float(config["extent_lower_quantile"]),
            extent_upper_quantile=float(config["extent_upper_quantile"]),
            minimum_gripper_width_m=float(config["minimum_gripper_width_m"]),
            maximum_gripper_width_m=float(config["maximum_gripper_width_m"]),
            width_clearance_m=float(config["width_clearance_m"]),
            maximum_object_extent_m=float(config["maximum_object_extent_m"]),
            point_support_reference=int(config["point_support_reference"]),
        )
    )


def build_mujoco_validation_service() -> MuJoCoValidationService:
    with (PROJECT_ROOT / "configs" / "default.toml").open("rb") as stream:
        config = tomllib.load(stream)["gongshu_validation"]
    if str(config["scene_transform"]) != "NORMALIZED_VALIDATION_SCENE":
        raise ValueError("unsupported Gongshu validation scene transform")
    if str(config["controller"]) != "MUJOCO_POSITION_DLS_IK":
        raise ValueError("unsupported Gongshu validation controller")

    def create_backend(request, director):
        from vision2grasp.simulation.native_panda_validation import (
            NativePandaValidation,
            NativePandaValidationConfig,
        )

        return NativePandaValidation(
            request,
            director,
            NativePandaValidationConfig(
                width=int(config["render_width"]),
                height=int(config["render_height"]),
                render_fps=int(config["render_fps"]),
                lift_height_m=float(config["lift_height_m"]),
                stable_window_s=float(config["stable_window_s"]),
            ),
        )

    return MuJoCoValidationService(create_backend)


class Vision2GraspApp:
    def __init__(
        self,
        *,
        phone_camera_config: PhoneLANConfig | None = None,
        spatial_provider: SpatialPerceptionProvider | None = None,
    ) -> None:
        self.camera = PhoneLANProvider(
            phone_camera_config or PhoneLANConfig(project_root=PROJECT_ROOT)
        )
        self._real_scene: RealSceneProcessor | None = None
        self._real_scene_lock = threading.Lock()
        self._simulation_lock = threading.Lock()
        self.target_perception = TargetPerceptionService(FastSAMTargetSegmenter())
        spatial_config = _spatial_perception_config()
        watchdog = build_spatial_watchdog(spatial_config)
        self.spatial_perception = SpatialPerceptionService(
            spatial_provider or build_spatial_perception_provider(spatial_config),
            watchdog=watchdog,
            benchmark_path=(
                PROJECT_ROOT / "artifacts" / "benchmarks" / "spatial-v0.5-cpu.json"
            ),
            compute_device=str(spatial_config["device"]),
            input_size=int(spatial_config["input_size"]),
        )
        self.grasp_planning = GraspPlanningService(build_grasp_planner())
        self.mujoco_validation = build_mujoco_validation_service()

    @property
    def real_scene(self) -> RealSceneProcessor:
        """Lazily retain the legacy perception path without using it for Camera v1."""
        with self._real_scene_lock:
            if self._real_scene is None:
                segmenter = UltralyticsYOLOSegmenter(
                    UltralyticsSegmenterConfig(target_class_names=("bottle",))
                )
                self._real_scene = RealSceneProcessor(
                    RealScenePerceptionPipeline(segmenter),
                    calibration_path=CALIBRATION_PATH,
                    target_fps=2.0,
                )
                self._real_scene.start()
            return self._real_scene

    def stop(self) -> None:
        self.mujoco_validation.reset()
        self.spatial_perception.close()
        self.camera.stop()
        if self._real_scene is not None:
            self._real_scene.stop()

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

    def analyze_phone_targets(self) -> dict[str, object]:
        """Freeze one real Phone RGB frame and generate selectable instances."""

        self.spatial_perception.reset()
        self.grasp_planning.reset()
        self.mujoco_validation.reset()
        return self.target_perception.analyze(self.camera.capture())

    def analyze_spatial(self, request: dict[str, Any]) -> dict[str, object]:
        """Analyze only the already-selected frozen Scene Snapshot."""

        self.grasp_planning.reset()
        self.mujoco_validation.reset()
        snapshot = self.target_perception.selected_scene_snapshot()
        return self.spatial_perception.start(
            snapshot,
            expected_snapshot_id=str(request["snapshot_id"]),
            expected_source_frame_id=int(request["source_frame_id"]),
            expected_target_instance_id=str(request["target_instance_id"]),
            expected_source_timestamp_s=float(request["source_timestamp_s"]),
        )

    def retry_spatial(self) -> dict[str, object]:
        self.grasp_planning.reset()
        self.mujoco_validation.reset()
        return self.spatial_perception.retry()

    def plan_grasp(self) -> dict[str, object]:
        """Plan only from the immutable SpatialResult and selected snapshot."""

        self.mujoco_validation.reset()
        return self.grasp_planning.plan(
            self.spatial_perception.current_observation(),
            self.target_perception.selected_scene_snapshot(),
        )

    def start_validation(self) -> dict[str, object]:
        """Create a normalized simulation-only request from the READY GraspPlan."""

        return self.mujoco_validation.start(self.grasp_planning.current_plan())

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
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".svg": "image/svg+xml"}

    def __init__(self, *args: Any, app: Vision2GraspApp, **kwargs: Any) -> None:
        self.app = app
        super().__init__(*args, directory=str(FRONTEND_ROOT), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep desktop logs useful by suppressing successful polling noise."""
        path = urlparse(self.path).path
        quiet_paths = {
            "/api/health",
            "/api/camera/state",
            "/api/real-scene/state",
            "/api/target-perception/state",
            "/api/spatial-perception/state",
            "/api/grasp-planning/state",
            "/api/mujoco-validation/state",
        }
        if (
            path in quiet_paths
            or path.startswith("/api/camera/live")
            or path.startswith("/api/real-scene/frame/")
        ):
            return
        super().log_message(format, *args)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(
                {
                    "schema_version": "vision2grasp.app-health/v1",
                    "status": "ok",
                    "capabilities": [
                        "camera.phone-lan/v1",
                        "camera.lan-live/webrtc",
                        "camera.lan-capture/original",
                        "target-perception.instance-mask/v1",
                        "target-selection.manual/v1",
                        "spatial-perception.monocular/v1",
                        "spatial-observation.camera-frame/v1",
                        "grasp-planning.geometric-pca/v1",
                        "grasp-plan/v1",
                        "mujoco-validation.normalized-scene/v1",
                        "mujoco-validation.cinematic-stream/v1",
                    ],
                    "camera_service": self.app.camera.snapshot()["service"]["status"],
                }
            )
            return
        if path == "/api/camera/state":
            self._send_json(self.app.camera.snapshot())
            return
        if path == "/api/camera/pairing-qr.png":
            self._send_binary(self.app.camera.pairing_qr_png(), "image/png")
            return
        if path == "/api/camera/setup-qr.png":
            self._send_binary(self.app.camera.setup_qr_png(), "image/png")
            return
        if path == "/api/camera/capture":
            capture = self.app.camera.latest_capture_bytes()
            if capture is None:
                self.send_error(HTTPStatus.NOT_FOUND, "capture not ready")
                return
            content_type, binary = capture
            self._send_binary(binary, content_type)
            return
        if path == "/api/camera/live.mjpeg":
            self._send_camera_mjpeg()
            return
        if path == "/api/target-perception/state":
            self._send_json(self.app.target_perception.snapshot())
            return
        if path == "/api/target-perception/overlay.jpg":
            overlay = self.app.target_perception.overlay_jpeg()
            if overlay is None:
                self.send_error(HTTPStatus.NOT_FOUND, "target overlay not ready")
                return
            self._send_binary(overlay, "image/jpeg")
            return
        if path == "/api/target-perception/scene-snapshot.jpg":
            snapshot = self.app.target_perception.scene_snapshot_jpeg()
            if snapshot is None:
                self.send_error(HTTPStatus.NOT_FOUND, "locked target snapshot not ready")
                return
            self._send_binary(snapshot, "image/jpeg")
            return
        if path == "/api/spatial-perception/state":
            self._send_json(self.app.spatial_perception.snapshot())
            return
        if path == "/api/spatial-perception/overview.jpg":
            overview = self.app.spatial_perception.overview_jpeg()
            if overview is None:
                self.send_error(HTTPStatus.NOT_FOUND, "spatial overview not ready")
                return
            self._send_binary(overview, "image/jpeg")
            return
        if path == "/api/grasp-planning/state":
            self._send_json(self.app.grasp_planning.snapshot())
            return
        if path == "/api/grasp-planning/overlay.jpg":
            overlay = self.app.grasp_planning.overlay_jpeg()
            if overlay is None:
                self.send_error(HTTPStatus.NOT_FOUND, "grasp overlay not ready")
                return
            self._send_binary(overlay, "image/jpeg")
            return
        if path == "/api/mujoco-validation/state":
            self._send_json(self.app.mujoco_validation.snapshot())
            return
        if path == "/api/mujoco-validation/live.mjpeg":
            self._send_validation_mjpeg()
            return
        if path == "/api/mujoco-validation/frame.jpg":
            frame = self.app.mujoco_validation.latest_frame()
            if frame is None:
                self.send_error(HTTPStatus.NOT_FOUND, "MuJoCo frame not ready")
                return
            self._send_binary(frame, "image/jpeg")
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
            if path == "/api/camera/pairing/refresh":
                self.app.camera.refresh_pairing()
                self._send_json({"status": "ok"})
                return
            if path == "/api/camera/capture/save":
                saved = self.app.camera.save_latest_capture()
                self._send_json({"status": "ok", "path": str(saved)})
                return
            if path == "/api/target-perception/analyze":
                self._send_json(self.app.analyze_phone_targets())
                return
            if path == "/api/target-perception/select":
                result = self.app.target_perception.select(
                    str(body["target_id"]),
                    source_frame_id=int(body["source_frame_id"]),
                )
                self._reset_downstream_after_target_change()
                self._send_json(result)
                return
            if path == "/api/target-perception/select-at":
                result = self.app.target_perception.select_at(
                    source_x=float(body["source_x"]),
                    source_y=float(body["source_y"]),
                    source_frame_id=int(body["source_frame_id"]),
                )
                self._reset_downstream_after_target_change()
                self._send_json(result)
                return
            if path == "/api/target-perception/reset":
                result = self.app.target_perception.reset()
                spatial = getattr(self.app, "spatial_perception", None)
                if spatial is not None:
                    spatial.reset()
                grasp = getattr(self.app, "grasp_planning", None)
                if grasp is not None:
                    grasp.reset()
                validation = getattr(self.app, "mujoco_validation", None)
                if validation is not None:
                    validation.reset()
                self._send_json(result)
                return
            if path == "/api/spatial-perception/analyze":
                self._send_json(
                    self.app.analyze_spatial(body),
                    status=HTTPStatus.ACCEPTED,
                )
                return
            if path == "/api/spatial-perception/retry":
                self._send_json(
                    self.app.retry_spatial(),
                    status=HTTPStatus.ACCEPTED,
                )
                return
            if path == "/api/spatial-perception/reset":
                self._send_json(self.app.spatial_perception.reset())
                return
            if path == "/api/grasp-planning/plan":
                self._send_json(self.app.plan_grasp())
                return
            if path == "/api/grasp-planning/reset":
                self._send_json(self.app.grasp_planning.reset())
                return
            if path == "/api/mujoco-validation/start":
                self._send_json(self.app.start_validation())
                return
            if path == "/api/mujoco-validation/reset":
                self._send_json(self.app.mujoco_validation.reset())
                return
            if path == "/api/mujoco-validation/camera-mode":
                self._send_json(self.app.mujoco_validation.set_camera_mode(str(body["mode"])))
                return
            if path == "/api/mujoco-validation/camera-manual":
                self._send_json(self.app.mujoco_validation.manual_camera(body))
                return
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
        except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
            self._send_json(
                {
                    "status": "error",
                    "error_code": getattr(error, "code", None),
                    "message": str(error),
                },
                status=400,
            )

    def _reset_downstream_after_target_change(self) -> None:
        for service_name in (
            "spatial_perception",
            "grasp_planning",
            "mujoco_validation",
        ):
            service = getattr(self.app, service_name, None)
            reset = getattr(service, "reset", None)
            if callable(reset):
                reset()

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
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _send_binary(self, payload: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _send_camera_mjpeg(self) -> None:
        boundary = b"xuanshu-camera-frame"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary.decode()}")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Connection", "close")
        self.end_headers()
        revision = -1
        try:
            while True:
                frame = self.app.camera.wait_for_live_jpeg(revision, timeout=2.0)
                if frame is None:
                    continue
                revision, jpeg = frame
                self.wfile.write(b"--" + boundary + b"\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _send_validation_mjpeg(self) -> None:
        boundary = b"gongshu-mujoco-frame"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary.decode()}")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Connection", "close")
        self.end_headers()
        revision = -1
        try:
            while True:
                frame = self.app.mujoco_validation.wait_for_frame(revision, timeout=2.0)
                if frame is None:
                    state = self.app.mujoco_validation.snapshot()["status"]
                    if state in {"WAITING", "FAILED", "SUCCESS"} and revision < 0:
                        return
                    continue
                revision, jpeg = frame
                self.wfile.write(b"--" + boundary + b"\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return


class LocalAppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Vision2Grasp app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--camera", default=None, help="Optional legacy camera index or stream URL.")
    parser.add_argument("--no-camera", action="store_true")
    parser.add_argument("--phone-https-port", type=int, default=8766)
    parser.add_argument("--phone-bootstrap-port", type=int, default=8767)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def _camera_value(value: str) -> int | str:
    stripped = value.strip()
    return int(stripped) if stripped.isdigit() else stripped


def main() -> int:
    args = _parse_args()
    for name, port in {
        "desktop": args.port,
        "phone HTTPS": args.phone_https_port,
        "phone bootstrap": args.phone_bootstrap_port,
    }.items():
        if not 1 <= port <= 65535:
            raise ValueError(f"{name} port must be between 1 and 65535")
    if len({args.port, args.phone_https_port, args.phone_bootstrap_port}) != 3:
        raise ValueError("desktop, phone HTTPS, and bootstrap ports must be different")
    app = Vision2GraspApp(
        phone_camera_config=PhoneLANConfig(
            project_root=PROJECT_ROOT,
            https_port=args.phone_https_port,
            bootstrap_port=args.phone_bootstrap_port,
        )
    )
    app.camera.start()
    camera_state = app.camera.snapshot()
    camera_service = camera_state["service"]
    print(
        "Jingwei Camera v1: "
        f"https://{camera_service['lan_address']}:{camera_service['https_port']} "
        "(private LAN, no cloud relay)"
    )
    if not args.no_camera and args.camera is not None:
        try:
            app.start_camera(_camera_value(args.camera))
        except (RuntimeError, ValueError) as error:
            print(f"camera startup warning: {error}")
    handler = partial(AppRequestHandler, app=app)
    try:
        server = LocalAppServer((args.host, args.port), handler)
    except BaseException:
        app.stop()
        raise
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
        app.stop()
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
