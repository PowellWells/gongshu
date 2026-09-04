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
from urllib.parse import parse_qs, urlparse
import webbrowser

import cv2
import numpy as np

from vision2grasp.camera import PhoneLANConfig, PhoneLANProvider
from vision2grasp.condition_processing import (
    ConditionExperimentProcessor,
    ConditionProcessingConfig,
    ConditionProcessor,
    ConditionProtocol,
    StressBlurType,
    StressLevel,
    StressStrategy,
)
from vision2grasp.contracts import RGBFrame
from vision2grasp.grasp_planning import (
    GRConvNetDetector,
    GRConvNetDetectorConfig,
    GraspPlanningService,
    PixelWiseTopKGraspPlanner,
    TopKGraspPlannerConfig,
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
from vision2grasp.target_perception import (
    FastSAMTargetSegmenter,
    FastSAMTargetSegmenterConfig,
    TargetPerceptionService,
)
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


def build_condition_processor() -> ConditionProcessor:
    with (PROJECT_ROOT / "configs" / "default.toml").open("rb") as stream:
        values = tomllib.load(stream)["condition_processing"]
    return ConditionProcessor(
        ConditionProcessingConfig(
            blur_mild_score=float(values["blur_mild_score"]),
            blur_moderate_score=float(values["blur_moderate_score"]),
            blur_severe_score=float(values["blur_severe_score"]),
            low_light_mild_score=float(values["low_light_mild_score"]),
            low_light_moderate_score=float(values["low_light_moderate_score"]),
            low_light_severe_score=float(values["low_light_severe_score"]),
            low_quality_score=float(values["low_quality_score"]),
            medium_quality_score=float(values["medium_quality_score"]),
            minimum_quality_gain=float(values["minimum_quality_gain"]),
            maximum_highlight_increase=float(values["maximum_highlight_increase"]),
        )
    )


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


def build_grasp_planner() -> PixelWiseTopKGraspPlanner:
    with (PROJECT_ROOT / "configs" / "default.toml").open("rb") as stream:
        document = tomllib.load(stream)
    config = document["gongshu_grasp_planning"]
    control = document["control"]
    if str(config["strategy"]) != "pixel_wise_topk_antipodal":
        raise ValueError("unsupported Gongshu grasp planning strategy")
    if str(config["backend"]) != "grconvnet_jacquard_rgbd":
        raise ValueError("unsupported Gongshu grasp detector backend")
    return PixelWiseTopKGraspPlanner(
        GRConvNetDetector(
            GRConvNetDetectorConfig(
                device=str(config["device"]),
                input_size=int(config["input_size"]),
                crop_margin=float(config["crop_margin"]),
            )
        ),
        TopKGraspPlannerConfig(
            top_k=int(config["top_k"]),
            minimum_quality=float(config["minimum_quality"]),
            minimum_points=int(config["minimum_points"]),
            extent_lower_quantile=float(config["extent_lower_quantile"]),
            extent_upper_quantile=float(config["extent_upper_quantile"]),
            minimum_gripper_width_m=float(control["minimum_gripper_width_m"]),
            maximum_gripper_width_m=float(control["maximum_gripper_width_m"]),
            maximum_object_extent_m=float(config["maximum_object_extent_m"]),
            minimum_valid_depth_ratio=float(config["minimum_valid_depth_ratio"]),
            minimum_geometry_confidence=float(config["minimum_geometry_confidence"]),
            minimum_mask_margin_ratio=float(config["minimum_mask_margin_ratio"]),
            point_support_reference=int(config["point_support_reference"]),
        )
    )


def build_mujoco_validation_service() -> MuJoCoValidationService:
    with (PROJECT_ROOT / "configs" / "default.toml").open("rb") as stream:
        document = tomllib.load(stream)
    config = document["gongshu_validation"]
    control = document["control"]
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
                recording_hz=float(config["recording_hz"]),
                lift_height_m=float(config["lift_height_m"]),
                stable_window_s=float(config["stable_window_s"]),
            ),
        )

    return MuJoCoValidationService(
        create_backend,
        failure_target_offset_m=tuple(
            float(value) for value in config["failure_target_offset_m"]
        ),
        max_session_recordings=int(config["max_session_recordings"]),
        minimum_gripper_width_m=float(control["minimum_gripper_width_m"]),
        maximum_gripper_width_m=float(control["maximum_gripper_width_m"]),
    )


class Vision2GraspApp:
    def __init__(
        self,
        *,
        phone_camera_config: PhoneLANConfig | None = None,
        spatial_provider: SpatialPerceptionProvider | None = None,
        grasp_planner: object | None = None,
    ) -> None:
        self.camera = PhoneLANProvider(
            phone_camera_config or PhoneLANConfig(project_root=PROJECT_ROOT)
        )
        self._real_scene: RealSceneProcessor | None = None
        self._real_scene_lock = threading.Lock()
        self._simulation_lock = threading.Lock()
        self.target_perception = TargetPerceptionService(
            FastSAMTargetSegmenter(FastSAMTargetSegmenterConfig(device="auto"))
        )
        self.condition_processor = build_condition_processor()
        self.condition_experiment = ConditionExperimentProcessor(self.condition_processor)
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
        self.grasp_planning = GraspPlanningService(grasp_planner or build_grasp_planner())
        self.mujoco_validation = build_mujoco_validation_service()
        self.grasp_planning.set_completion_callback(
            self.mujoco_validation.record_planning_rejection
        )

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
        self.mujoco_validation.close()
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

    def analyze_phone_targets(self, request: dict[str, Any] | None = None) -> dict[str, object]:
        """Freeze one real Phone RGB frame and generate selectable instances."""

        self.spatial_perception.reset()
        self.grasp_planning.reset()
        self.mujoco_validation.reset()
        body = request or {}
        conditioned = self.condition_experiment.process(
            self.camera.capture(),
            self._condition_protocol(body),
            strategy=self._stress_strategy(body),
            level=self._stress_level(body),
            blur_type=self._stress_blur_type(body),
            random_seed=self._stress_seed(body),
            research_mode=str(body.get("mode", "RESEARCH")).upper() == "RESEARCH",
        )
        return self.target_perception.analyze(conditioned)

    def track_phone_target(
        self, request: dict[str, Any] | None = None
    ) -> dict[str, object]:
        """Update only the high-resolution overlay for a locked demo target."""

        body = request or {}
        frame = self.camera.capture()
        if (
            str(body.get("mode", "RESEARCH")).upper() == "RESEARCH"
            and self._condition_protocol(body) is not ConditionProtocol.NORMAL
        ):
            frame = self.condition_experiment.process(
                frame,
                self._condition_protocol(body),
                strategy=self._stress_strategy(body),
                level=self._stress_level(body),
                blur_type=self._stress_blur_type(body),
                random_seed=self._stress_seed(body),
                research_mode=True,
            ).processed_frame
        return self.target_perception.track(frame)

    def process_live_condition_jpeg(
        self, jpeg: bytes, revision: int, request: dict[str, Any]
    ) -> bytes:
        """Render the final research Pipeline Frame for the Live RGB stream."""

        if (
            str(request.get("view", "pipeline")).lower() == "raw"
            or str(request.get("mode", "RESEARCH")).upper() != "RESEARCH"
            or self._condition_protocol(request) is ConditionProtocol.NORMAL
        ):
            return jpeg
        bgr = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("无法解码实时视觉帧 Live RGB frame decode failed")
        frame = RGBFrame(
            frame_id=max(0, int(revision)),
            timestamp_s=float(max(0, int(revision))),
            camera_name="phone-live-preview",
            rgb=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB),
        )
        conditioned = self.condition_experiment.process(
            frame,
            self._condition_protocol(request),
            strategy=self._stress_strategy(request),
            level=self._stress_level(request),
            blur_type=self._stress_blur_type(request),
            random_seed=self._stress_seed(request),
            research_mode=True,
        )
        encoded, output = cv2.imencode(
            ".jpg",
            cv2.cvtColor(conditioned.processed_frame.rgb, cv2.COLOR_RGB2BGR),
            [cv2.IMWRITE_JPEG_QUALITY, 88],
        )
        if not encoded:
            raise RuntimeError("无法编码条件预览 Condition preview encode failed")
        return output.tobytes()

    @staticmethod
    def _condition_protocol(body: dict[str, Any]) -> ConditionProtocol:
        try:
            return ConditionProtocol(
                str(body.get("condition", "NORMAL")).upper().replace("-", "_")
            )
        except ValueError as error:
            raise ValueError("视觉条件无效 Invalid visual condition") from error

    @staticmethod
    def _stress_strategy(body: dict[str, Any]) -> StressStrategy:
        try:
            return StressStrategy(str(body.get("strategy", "STRESS_ONLY")).upper())
        except ValueError as error:
            raise ValueError("实验策略无效 Invalid stress strategy") from error

    @staticmethod
    def _stress_level(body: dict[str, Any]) -> StressLevel:
        try:
            return StressLevel(str(body.get("level", "MODERATE")).upper())
        except ValueError as error:
            raise ValueError("压力等级无效 Invalid stress level") from error

    @staticmethod
    def _stress_blur_type(body: dict[str, Any]) -> StressBlurType:
        try:
            return StressBlurType(str(body.get("blur_type", "GAUSSIAN")).upper())
        except ValueError as error:
            raise ValueError("模糊类型无效 Invalid blur type") from error

    @staticmethod
    def _stress_seed(body: dict[str, Any]) -> int:
        try:
            return int(body.get("random_seed", 7))
        except (TypeError, ValueError) as error:
            raise ValueError("随机种子无效 Invalid random seed") from error

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

    def plan_grasp(self, request: dict[str, Any] | None = None) -> dict[str, object]:
        """Plan only from the immutable SpatialResult and selected snapshot."""

        self.mujoco_validation.reset()
        body = request or {}
        observation = self.spatial_perception.current_observation()
        snapshot = self.target_perception.selected_scene_snapshot()
        if snapshot is None:
            raise RuntimeError("no selected Scene Snapshot is available for grasp planning")
        requested_snapshot_id = str(body.get("snapshot_id", "")).strip()
        if requested_snapshot_id and requested_snapshot_id != snapshot.snapshot_id:
            raise ValueError("Grasp Planning request does not match selected Scene Snapshot")
        return self.grasp_planning.plan(
            observation,
            snapshot,
            mode=str(body.get("mode", "RESEARCH")),
        )

    def start_validation(self, request: dict[str, Any] | None = None) -> dict[str, object]:
        """Create one normalized attempt from a ready or rejected candidate."""

        body = request or {}
        outcome = self.grasp_planning.current_outcome()
        snapshot = self.target_perception.selected_scene_snapshot()
        if snapshot is None:
            raise RuntimeError("no selected Scene Snapshot is available for simulation")
        candidate = outcome.plan if outcome.plan is not None else (
            outcome.candidates[0] if outcome.candidates else None
        )
        if candidate is None:
            raise RuntimeError("Simulation Attempt is unavailable because no candidate exists")
        requested_target_id = str(body.get("target_id", "")).strip()
        candidate_target_id = (
            candidate.target_id if outcome.plan is not None else candidate.target_instance_id
        )
        if requested_target_id and requested_target_id != candidate_target_id:
            raise ValueError("Validation request does not match the selected simulation candidate")
        scenario = str(body.get("scenario", "NOMINAL"))
        if outcome.plan is not None:
            return self.mujoco_validation.start(
                outcome.plan, scenario=scenario, snapshot=snapshot
            )
        return self.mujoco_validation.start_rejected_attempt(
            outcome, scenario=scenario, snapshot=snapshot
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
                        "condition-processing.classical/v1",
                        "condition-stress-simulation.reproducible/v1",
                        "condition-report.provenance/v1",
                        "pipeline-uncertainty-interface/v1",
                        "target-selection.manual/v1",
                        "target-tracking.short-horizon/v1",
                        "target-lock-metadata/v1",
                        "spatial-perception.monocular/v1",
                        "spatial-observation.camera-frame/v1",
                        "grasp-planning.geometric-pca/v1",
                        "grasp-plan/v1",
                        "mujoco-validation.normalized-scene/v1",
                        "mujoco-validation.cinematic-stream/v1",
                        "mujoco-validation.session-recording/v1",
                        "mujoco-validation.state-playback/v1",
                        "mujoco-validation.explicit-save/v1",
                        "mujoco-validation.real-appearance-proxy/v1",
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
        condition_frame_prefix = "/api/target-perception/condition-frame/"
        if path.startswith(condition_frame_prefix) and path.endswith(".jpg"):
            kind = path[len(condition_frame_prefix) : -4]
            if kind not in {"raw", "degraded", "enhanced", "pipeline"}:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            payload = self.app.target_perception.condition_frame_jpeg(kind)
            if payload is None:
                self.send_error(HTTPStatus.NOT_FOUND, "条件实验帧不可用 Condition frame unavailable")
                return
            self._send_binary(payload, "image/jpeg")
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
        if path == "/api/grasp-planning/view.jpg":
            layer = parse_qs(urlparse(self.path).query).get("layer", ["candidates"])[0]
            view = self.app.grasp_planning.view_jpeg(layer)
            if view is None:
                self.send_error(HTTPStatus.NOT_FOUND, "grasp view not ready")
                return
            self._send_binary(view, "image/jpeg")
            return
        if path == "/api/mujoco-validation/state":
            self._send_json(self.app.mujoco_validation.snapshot())
            return
        if path == "/api/mujoco-validation/history":
            self._send_json(self.app.mujoco_validation.session_history())
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
                self._send_json(
                    self.app.analyze_phone_targets(body)
                    if body
                    else self.app.analyze_phone_targets()
                )
                return
            if path == "/api/target-perception/track":
                self._send_json(self.app.track_phone_target(body))
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
                self._send_json(self.app.plan_grasp(body), status=HTTPStatus.ACCEPTED)
                return
            if path == "/api/grasp-planning/reset":
                self._send_json(self.app.grasp_planning.reset())
                return
            if path == "/api/mujoco-validation/start":
                self._send_json(self.app.start_validation(body))
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
            if path == "/api/mujoco-validation/playback":
                self._send_json(self.app.mujoco_validation.playback_control(body))
                return
            if path == "/api/mujoco-validation/recording/open":
                self._send_json(
                    self.app.mujoco_validation.open_recording(
                        str(body["recording_id"]), saved=bool(body.get("saved", False))
                    )
                )
                return
            if path == "/api/mujoco-validation/recording/save":
                self._send_json(self.app.mujoco_validation.save_current_recording())
                return
            if path == "/api/mujoco-validation/export-video":
                self._send_json(self.app.mujoco_validation.export_video())
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
        query = {
            name: values[0]
            for name, values in parse_qs(urlparse(self.path).query).items()
            if values
        }
        try:
            while True:
                frame = self.app.camera.wait_for_live_jpeg(revision, timeout=2.0)
                if frame is None:
                    continue
                revision, jpeg = frame
                try:
                    jpeg = self.app.process_live_condition_jpeg(jpeg, revision, query)
                except (TypeError, ValueError, RuntimeError):
                    # Keep the live transport available; invalid settings are
                    # reported by the Analyze endpoint before experiment data is recorded.
                    pass
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
