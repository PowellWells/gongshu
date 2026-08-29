"""Thread-safe Grasp Planning service tied to a SpatialObservation."""

from __future__ import annotations

import threading
from typing import Final

from vision2grasp.spatial_perception import SpatialObservation
from vision2grasp.target_perception import TargetSceneSnapshot

from .contracts import GraspPlan
from .planner import GeometricGraspPlanner, GraspPlanningError
from .visualization import encode_jpeg, render_grasp_overlay


GRASP_PLANNING_SCHEMA_VERSION: Final = "gongshu.grasp-planning/v1"


class GraspPlanningService:
    def __init__(self, planner: GeometricGraspPlanner | None = None) -> None:
        self._planner = planner or GeometricGraspPlanner()
        self._lock = threading.RLock()
        self._guard = threading.Lock()
        self._status = "WAITING"
        self._message = "等待抓取规划 WAITING"
        self._error_code: str | None = None
        self._revision = 0
        self._plan: GraspPlan | None = None
        self._candidate_count = 0
        self._overlay_jpeg: bytes | None = None

    def plan(self, observation: SpatialObservation, snapshot: TargetSceneSnapshot) -> dict[str, object]:
        if not self._guard.acquire(blocking=False):
            raise RuntimeError("grasp planning is already running")
        try:
            with self._lock:
                self._status = "PLANNING"
                self._message = "正在生成与评估抓取候选 Grasp Planning"
                self._error_code = None
                self._plan = None
                self._overlay_jpeg = None
                self._revision += 1
            self._validate_association(observation, snapshot)
            plan, candidates = self._planner.plan(observation)
            overlay = encode_jpeg(render_grasp_overlay(snapshot, plan))
            with self._lock:
                self._plan = plan
                self._candidate_count = len(candidates)
                self._overlay_jpeg = overlay
                self._status = "READY"
                self._message = "抓取规划完成 GRASP READY"
                self._revision += 1
                return self.snapshot()
        except Exception as error:
            with self._lock:
                self._status = "FAILED"
                self._message = str(error) or "抓取规划失败 GRASP FAILED"
                self._error_code = getattr(error, "code", "GRASP_PLANNING_FAILED")
                self._plan = None
                self._candidate_count = 0
                self._overlay_jpeg = None
                self._revision += 1
                return self.snapshot()
        finally:
            self._guard.release()

    def reset(self) -> dict[str, object]:
        if self._guard.locked():
            raise RuntimeError("cannot reset while grasp planning is running")
        with self._lock:
            self._status = "WAITING"
            self._message = "等待抓取规划 WAITING"
            self._error_code = None
            self._plan = None
            self._candidate_count = 0
            self._overlay_jpeg = None
            self._revision += 1
            return self.snapshot()

    def current_plan(self) -> GraspPlan:
        with self._lock:
            if self._plan is None:
                raise RuntimeError("GraspPlan is not ready")
            return self._plan

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "schema_version": GRASP_PLANNING_SCHEMA_VERSION,
                "status": self._status,
                "message": self._message,
                "error_code": self._error_code,
                "revision": self._revision,
                "candidate_count": self._candidate_count,
                "plan": None if self._plan is None else self._plan.public_metadata(),
                "media": {"overlay_available": self._overlay_jpeg is not None},
            }

    def overlay_jpeg(self) -> bytes | None:
        with self._lock:
            return None if self._overlay_jpeg is None else bytes(self._overlay_jpeg)

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

