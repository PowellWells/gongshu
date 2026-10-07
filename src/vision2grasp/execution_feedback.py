"""Execution evidence projected into a user-facing Gongshu chat event.

The execution result remains the source of truth.  This module only translates
the existing MuJoCo/robot result, state history, and telemetry into a stable
machine-readable event plus a concise human-facing summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Mapping


FEEDBACK_SCHEMA_VERSION = "gongshu.grasp-execution-feedback/v1"
CHAT_EVENT_SCHEMA_VERSION = "gongshu.chat-event/v1"


def _text(value: object | None, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _as_float(value: object | None) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _attempt_metadata(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    request = snapshot.get("request")
    if not isinstance(request, Mapping):
        return {}
    attempt = request.get("simulation_attempt")
    if isinstance(attempt, Mapping):
        return attempt
    plan = request.get("grasp_plan")
    return plan if isinstance(plan, Mapping) else {}


def _state_history(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    history = snapshot.get("state_history")
    if not isinstance(history, list):
        return []
    return [dict(item) for item in history if isinstance(item, Mapping)]


def _stage_for_state(state: str) -> str:
    return {
        "HOME": "approach",
        "INITIALIZING": "approach",
        "PRE_GRASP": "approach",
        "APPROACH": "approach",
        "ALIGN": "approach",
        "CLOSE": "closure",
        "LIFT": "lift",
        "VERIFY": "hold",
        "SUCCESS": "complete",
        "FAILED": "hold",
    }.get(state.upper(), "approach")


def _failure_type(reason: str, *, system_error: bool) -> str | None:
    if not reason and not system_error:
        return None
    return {
        "COLLISION_ABORT": "approach_collision",
        "NO_CONTACT": "miss_or_empty_closure",
        "CONTACT_LOSS": "slip_or_drop",
        "SLIP": "slip_or_drop",
        "NO_LIFT": "insufficient_contact",
        "UNSTABLE_GRASP": "unstable_grasp",
        "EXECUTION_TIMEOUT": "execution_timeout",
        "EXECUTION_ERROR": "unknown_failure",
    }.get(reason, "unknown_failure")


def _stage(snapshot: Mapping[str, Any], reason: str, success: bool) -> str:
    if success:
        return "complete"
    if reason == "NO_CONTACT":
        return "contact"
    if reason in {"CONTACT_LOSS", "SLIP", "NO_LIFT"}:
        return "lift"
    if reason == "UNSTABLE_GRASP":
        return "hold"
    history = _state_history(snapshot)
    for item in reversed(history):
        state = _text(item.get("state")).upper()
        if state not in {"FAILED", "SUCCESS"}:
            return _stage_for_state(state)
    return "approach"


def _suggested_action(failure_type: str | None, success: bool) -> str:
    if success:
        return "task_complete"
    return {
        "approach_collision": "reobserve_and_replan",
        "miss_or_empty_closure": "select_candidate_with_better_contact_support",
        "slip_or_drop": "select_more_stable_candidate",
        "insufficient_contact": "reobserve_and_replan",
        "unstable_grasp": "select_more_stable_candidate",
        "execution_timeout": "inspect_executor_and_retry_safely",
        "unknown_failure": "inspect_system_status_before_retry",
    }.get(failure_type or "unknown_failure", "inspect_system_status_before_retry")


def _evidence_lines(
    *,
    reason: str,
    success: bool,
    metrics: Mapping[str, Any],
) -> list[str]:
    lines: list[str] = []
    if metrics.get("gripper_close_executed") is True:
        lines.append("夹爪闭合动作已执行")
    if metrics.get("contact_observed") is True:
        lines.append("执行证据中观测到夹爪与目标接触")
    elif metrics.get("contact_observed") is False:
        lines.append("执行证据中未观测到有效接触")
    lift_height = metrics.get("lift_height_m")
    if isinstance(lift_height, (int, float)):
        lines.append(f"记录到目标抬升高度 {float(lift_height) * 1000:.1f} mm")
    if metrics.get("stable_window_passed") is True:
        lines.append("保持窗口通过，目标状态稳定")
    elif metrics.get("stable_window_passed") is False and reason == "UNSTABLE_GRASP":
        lines.append("保持窗口未通过，目标状态不稳定")
    if metrics.get("collision") is True:
        lines.append("检测到无效桌面碰撞，动作已终止")
    if reason in {"SLIP", "CONTACT_LOSS"}:
        lines.append("抬升阶段后接触证据丢失，判定为滑落或脱离")
    if not lines:
        lines.append("执行器已完成终态记录，但可用证据有限")
    if success:
        return lines
    return lines


def _summary(
    *,
    target: str,
    success: bool,
    stage: str,
    failure_type: str | None,
    reason: str,
    system_error: bool,
) -> str:
    if success:
        return f"目标 {target} 已完成 Approach → Contact → Closure → Lift → Hold。物体已稳定抬升并保持，本次任务完成。"
    if system_error:
        return "系统未能完成本次抓取执行：执行器没有提供可验证的终态证据，动作已安全终止。"
    return {
        "approach_collision": f"目标 {target} 在 {stage} 阶段检测到碰撞，动作已安全终止。",
        "miss_or_empty_closure": f"目标 {target} 已进入闭合阶段，但没有观测到有效接触，可能抓空。",
        "slip_or_drop": f"目标 {target} 曾进入抬升阶段，但接触证据随后丢失，判定为滑落或脱离。",
        "insufficient_contact": f"目标 {target} 完成闭合但没有达到有效抬升条件，接触支撑不足。",
        "unstable_grasp": f"目标 {target} 达到抬升条件，但保持窗口未通过，抓取状态不稳定。",
        "execution_timeout": f"目标 {target} 的抓取执行超时，动作已安全终止。",
        "unknown_failure": f"目标 {target} 在 {stage} 阶段失败；当前证据不足以进一步细分原因。",
    }.get(failure_type or "unknown_failure", f"目标 {target} 执行失败（{reason or 'UNKNOWN'}）。")


@dataclass(frozen=True, slots=True)
class GraspExecutionFeedback:
    """Stable boundary between execution evidence and UI chat."""

    event_id: str
    task_id: str
    attempt_id: str
    target_object: str
    grasp_candidate_id: str
    execution_timestamp: str
    success: bool
    stage: str
    failure_type: str | None
    source_failure_reason: str | None
    failure_evidence: Mapping[str, Any]
    confidence: float | None
    relevant_metrics: Mapping[str, Any]
    summary: str
    suggested_next_action: str
    message_type: str

    def public_metadata(self) -> dict[str, Any]:
        return {
            "event": "grasp_execution_feedback",
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "event_id": self.event_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "target": self.target_object,
            "candidate_id": self.grasp_candidate_id,
            "execution_timestamp": self.execution_timestamp,
            "success": self.success,
            "stage": self.stage,
            "failure_type": self.failure_type,
            "source_failure_reason": self.source_failure_reason,
            "failure_evidence": dict(self.failure_evidence),
            "confidence": self.confidence,
            "relevant_metrics": dict(self.relevant_metrics),
            "summary": self.summary,
            "recommended_action": self.suggested_next_action,
            "message_type": self.message_type,
        }

    def chat_event(self) -> dict[str, Any]:
        metadata = self.public_metadata()
        return {
            "event": "grasp_execution_feedback",
            "schema_version": CHAT_EVENT_SCHEMA_VERSION,
            "event_id": self.event_id,
            "message_id": self.event_id,
            "message_type": self.message_type,
            "text": self.summary,
            "metadata": metadata,
        }


def build_grasp_execution_feedback(
    snapshot: Mapping[str, Any],
    *,
    task_id: str | None = None,
    event_id: str | None = None,
    execution_timestamp: str | None = None,
) -> GraspExecutionFeedback:
    """Build feedback from the existing terminal validation snapshot.

    No sensor or outcome is inferred from natural language.  Missing result
    data is treated as a system error and is kept separate from execution
    failure evidence.
    """

    attempt = _attempt_metadata(snapshot)
    result = snapshot.get("result")
    result_data = dict(result) if isinstance(result, Mapping) else {}
    telemetry = snapshot.get("telemetry")
    telemetry_data = dict(telemetry) if isinstance(telemetry, Mapping) else {}
    state = _text(result_data.get("state"), _text(snapshot.get("status"), "FAILED")).upper()
    success = state == "SUCCESS"
    reason = _text(result_data.get("reason"), _text(snapshot.get("reason"))).upper()
    system_error = not bool(result_data) and state == "FAILED"
    public_reason = "EXECUTION_ERROR" if system_error else reason
    failure_type = _failure_type(reason, system_error=system_error)
    target = _text(attempt.get("target_id"), "unknown target")
    candidate = _text(
        attempt.get("candidate_id"),
        _text(attempt.get("best_candidate_id"), "unknown candidate"),
    )
    attempt_id = _text(attempt.get("attempt_id"), f"attempt-{target}-{candidate}")
    resolved_task_id = _text(task_id, _text(attempt.get("task_id"), f"task-{attempt_id}"))
    lift_height = _as_float(result_data.get("lift_height_m"))
    if lift_height is None:
        lift_height = _as_float(telemetry_data.get("lift_height_m"))
    collision = result_data.get("invalid_table_collision")
    if collision is None:
        collision = telemetry_data.get("collision")
    contact_observed: bool | None = {
        "NO_CONTACT": False,
        "CONTACT_LOSS": False,
        "SLIP": True,
    }.get(reason)
    metrics: dict[str, Any] = {
        "state_machine_complete": result_data.get("state_machine_complete"),
        "gripper_close_executed": result_data.get("gripper_close_executed"),
        "lift_height_m": lift_height,
        "object_lifted": None if lift_height is None else lift_height > 0.0,
        "stable_window_passed": result_data.get("stable_window_passed"),
        "collision": collision,
        "contact_observed": contact_observed,
    }
    stage = _stage(snapshot, reason, success)
    evidence = {
        "source": "MuJoCo ValidationResult + state_history + telemetry",
        "source_failure_reason": public_reason or None,
        "terminal_state": state,
        "observed_signals": {
            key: value for key, value in metrics.items() if value is not None
        },
        "state_history": _state_history(snapshot),
        "failure_detail_present": bool(result_data.get("failure_detail")),
    }
    lines = _evidence_lines(reason=reason, success=success, metrics=metrics)
    if system_error:
        lines = ["未收到可验证的 ValidationResult；详细异常仅保留在开发日志中。"]
    summary = _summary(
        target=target,
        success=success,
        stage=stage,
        failure_type=failure_type,
        reason=reason,
        system_error=system_error,
    )
    if not success and not system_error and lines:
        summary = f"{summary}"
    return GraspExecutionFeedback(
        event_id=_text(event_id, f"grasp-feedback-{attempt_id}"),
        task_id=resolved_task_id,
        attempt_id=attempt_id,
        target_object=target,
        grasp_candidate_id=candidate,
        execution_timestamp=_text(execution_timestamp, _iso_now()),
        success=success,
        stage=stage,
        failure_type=failure_type,
        source_failure_reason=public_reason or None,
        failure_evidence={**evidence, "human_evidence_lines": lines},
        confidence=1.0 if result_data else 0.0,
        relevant_metrics=metrics,
        summary=summary,
        suggested_next_action=_suggested_action(failure_type, success),
        message_type="grasp_feedback" if not system_error else "system_error",
    )


class ChatEventStore:
    """Small process-local event history used by the existing Gongshu page."""

    def __init__(self, *, max_events: int = 128) -> None:
        self._max_events = max(1, int(max_events))
        self._lock = RLock()
        self._events: list[dict[str, Any]] = []

    def append_once(self, event: Mapping[str, Any]) -> bool:
        event_id = _text(event.get("event_id"), _text(event.get("message_id")))
        if not event_id:
            raise ValueError("chat event requires event_id")
        with self._lock:
            if any(item.get("event_id") == event_id for item in self._events):
                return False
            self._events.append(dict(event))
            del self._events[:-self._max_events]
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            events = [dict(event) for event in self._events]
        return {
            "schema_version": CHAT_EVENT_SCHEMA_VERSION,
            "events": events,
            "count": len(events),
            "latest_event_id": events[-1].get("event_id") if events else None,
        }
