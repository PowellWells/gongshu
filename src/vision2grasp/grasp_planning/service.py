"""Asynchronous target-bound Top-K grasp planning service."""

from __future__ import annotations

import threading
import time
from typing import Final
from uuid import uuid4

from vision2grasp.spatial_perception import SpatialObservation
from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import GraspPlan, GraspPlanningOutcome, GraspStage, PlanningMode
from .planner import GeometricGraspPlanner, GraspPlanningError
from .visualization import encode_jpeg, render_grasp_overlay, render_grasp_views


GRASP_PLANNING_SCHEMA_VERSION: Final = "gongshu.grasp-planning-job/v2"


class GraspPlanningService:
    def __init__(self, planner: object | None = None) -> None:
        # The retained geometric planner is available only for source
        # compatibility. The app explicitly injects PixelWiseTopKGraspPlanner.
        self._planner = planner or GeometricGraspPlanner()
        self._lock = threading.RLock()
        self._status = "WAITING"
        self._stage = GraspStage.WAITING
        self._message = "等待抓取规划 WAITING"
        self._error_code: str | None = None
        self._revision = 0
        self._generation = 0
        self._job_id: str | None = None
        self._job_started_at = 0.0
        self._stage_started_at = 0.0
        self._stage_details: dict[str, object] = {}
        self._plan: GraspPlan | None = None
        self._outcome: GraspPlanningOutcome | None = None
        self._candidate_count = 0
        self._views: dict[str, bytes] = {}
        self._thread: threading.Thread | None = None
        self._mode = PlanningMode.RESEARCH

    def plan(
        self,
        observation: SpatialObservation,
        snapshot: TargetSceneSnapshot,
        *,
        mode: PlanningMode | str = PlanningMode.RESEARCH,
    ) -> dict[str, object]:
        selected_mode = mode if isinstance(mode, PlanningMode) else PlanningMode(str(mode).upper())
        self._validate_association(observation, snapshot)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("grasp planning is already running")
            self._generation += 1
            generation = self._generation
            job_id = f"grasp-{uuid4().hex}"
            now = time.monotonic()
            self._status = "PLANNING"
            self._stage = GraspStage.QUEUED
            self._message = "抓取规划任务已排队 QUEUED"
            self._error_code = None
            self._job_id = job_id
            self._job_started_at = now
            self._stage_started_at = now
            self._stage_details = {}
            self._plan = None
            self._outcome = None
            self._candidate_count = 0
            self._views = {}
            self._mode = selected_mode
            self._revision += 1
            thread = threading.Thread(
                target=self._run,
                args=(generation, job_id, observation, snapshot, selected_mode),
                name=f"gongshu-grasp-{job_id[-8:]}",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return self.snapshot()

    def reset(self) -> dict[str, object]:
        with self._lock:
            self._generation += 1
            self._status = "WAITING"
            self._stage = GraspStage.WAITING
            self._message = "等待抓取规划 WAITING"
            self._error_code = None
            self._job_id = None
            self._stage_details = {}
            self._plan = None
            self._outcome = None
            self._candidate_count = 0
            self._views = {}
            self._revision += 1
            return self.snapshot()

    def current_plan(self) -> GraspPlan:
        with self._lock:
            if self._plan is None:
                raise RuntimeError("GraspPlan is not GRASP_READY")
            return self._plan

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            active = self._status == "PLANNING"
            now = time.monotonic()
            total_elapsed = now - self._job_started_at if active else self._stage_details.get("total_elapsed_s", 0.0)
            stage_elapsed = now - self._stage_started_at if active else self._stage_details.get("stage_elapsed_s", 0.0)
            outcome = self._outcome
            candidates = (
                []
                if outcome is None
                else [candidate.public_metadata() for candidate in outcome.candidates]
            )
            executable_count = sum(1 for item in candidates if item["feasibility"] == "EXECUTABLE")
            return {
                "schema_version": GRASP_PLANNING_SCHEMA_VERSION,
                "job_id": self._job_id,
                "status": self._status,
                "stage": self._stage.value,
                "message": self._message,
                "error_code": self._error_code,
                "revision": self._revision,
                "mode": self._mode.value,
                "candidate_count": self._candidate_count,
                "executable_count": executable_count,
                "rejected_count": len(candidates) - executable_count,
                "candidates": candidates,
                "plan": None if self._plan is None else self._plan.public_metadata(),
                "visualization_request": (
                    None if outcome is None else outcome.visualization_request()
                ),
                "maps": None if outcome is None else outcome.maps.public_metadata(),
                "timing": {
                    "stage_elapsed_s": float(stage_elapsed),
                    "total_elapsed_s": float(total_elapsed),
                    "eta_s": None,
                    "model_load_s": (
                        None if outcome is None else outcome.maps.model_load_time_s
                    ),
                    "inference_s": (
                        None if outcome is None else outcome.maps.inference_time_s
                    ),
                    "model_was_ready": (
                        None if outcome is None else outcome.maps.model_was_ready
                    ),
                },
                "stage_details": dict(self._stage_details),
                "preflight": {
                    "graspable": executable_count > 0,
                    "executable_candidates": executable_count,
                    "recommendation": (
                        "EXECUTABLE_TARGET"
                        if executable_count > 0
                        else (self._error_code or "WAITING")
                    ),
                },
                "media": {
                    "available_layers": list(self._views),
                    "overlay_available": "candidates" in self._views,
                },
            }

    def view_jpeg(self, layer: str = "candidates") -> bytes | None:
        with self._lock:
            value = self._views.get(layer)
            return None if value is None else bytes(value)

    def overlay_jpeg(self) -> bytes | None:
        return self.view_jpeg("candidates")

    def _run(
        self,
        generation: int,
        job_id: str,
        observation: SpatialObservation,
        snapshot: TargetSceneSnapshot,
        mode: PlanningMode,
    ) -> None:
        try:
            if isinstance(self._planner, GeometricGraspPlanner):
                self._progress(generation, job_id, GraspStage.CANDIDATE_EXTRACTION, None)
                plan, candidates = self._planner.plan(observation)
                overlay = encode_jpeg(render_grasp_overlay(snapshot, plan))
                with self._lock:
                    if not self._is_current(generation, job_id):
                        return
                    elapsed = time.monotonic() - self._job_started_at
                    self._plan = plan
                    self._candidate_count = len(candidates)
                    self._views = {"candidates": overlay}
                    self._status = "GRASP_READY"
                    self._stage = GraspStage.GRASP_READY
                    self._message = "抓取规划完成 GRASP_READY"
                    self._stage_details = {"total_elapsed_s": elapsed, "stage_elapsed_s": 0.0}
                    self._revision += 1
                return
            outcome = self._planner.plan(
                observation,
                snapshot,
                mode=mode,
                progress=lambda stage, details=None: self._progress(
                    generation, job_id, stage, details
                ),
            )
            rendered = render_grasp_views(snapshot, outcome, mode)
            views = {name: encode_jpeg(image) for name, image in rendered.items()}
            with self._lock:
                if not self._is_current(generation, job_id):
                    return
                self._outcome = outcome
                self._plan = outcome.plan
                self._candidate_count = len(outcome.candidates)
                self._views = views
                elapsed = time.monotonic() - self._job_started_at
                self._stage_details = {
                    "total_elapsed_s": elapsed,
                    "stage_elapsed_s": 0.0,
                    "compute_device": outcome.maps.compute_device,
                    "model_was_ready": outcome.maps.model_was_ready,
                }
                if outcome.ready:
                    self._status = "GRASP_READY"
                    self._stage = GraspStage.GRASP_READY
                    self._message = "最佳可执行抓取已就绪 GRASP_READY"
                    self._error_code = None
                else:
                    self._status = "PLANNING_REJECTED"
                    self._stage = GraspStage.REJECTED
                    self._error_code = outcome.rejection_reason or "NO_VALID_CANDIDATE"
                    self._message = f"规划拒绝 PLANNING_REJECTED · {self._error_code}"
                self._revision += 1
        except Exception as error:
            with self._lock:
                if not self._is_current(generation, job_id):
                    return
                elapsed = time.monotonic() - self._job_started_at
                self._status = "GRASP_ERROR"
                self._stage = GraspStage.FAILED
                self._message = str(error) or "抓取规划错误 GRASP_ERROR"
                self._error_code = getattr(error, "code", "GRASP_PLANNING_FAILED")
                self._plan = None
                self._outcome = None
                self._candidate_count = 0
                self._views = {}
                self._stage_details = {"total_elapsed_s": elapsed, "stage_elapsed_s": 0.0}
                self._revision += 1

    def _progress(
        self,
        generation: int,
        job_id: str,
        stage: GraspStage,
        details: object | None,
    ) -> None:
        with self._lock:
            if not self._is_current(generation, job_id):
                return
            self._stage = stage
            self._stage_started_at = time.monotonic()
            if isinstance(details, dict):
                self._stage_details.update(details)
            self._message = f"抓取规划 {stage.value}"
            self._revision += 1

    def _is_current(self, generation: int, job_id: str) -> bool:
        return self._generation == generation and self._job_id == job_id

    @staticmethod
    def _validate_association(observation: SpatialObservation, snapshot: TargetSceneSnapshot) -> None:
        if observation.snapshot_id != snapshot.snapshot_id:
            raise GraspPlanningError("SpatialResult snapshot mismatch")
        if observation.source_frame_id != snapshot.frame.frame_id:
            raise GraspPlanningError("SpatialResult frame mismatch")
        if observation.target_instance_id != snapshot.target.instance_id:
            raise GraspPlanningError("SpatialResult target mismatch")
        if observation.source_timestamp_s != snapshot.frame.timestamp_s:
            raise GraspPlanningError("SpatialResult timestamp mismatch")
