from __future__ import annotations

import unittest

from vision2grasp.execution_feedback import ChatEventStore, build_grasp_execution_feedback
from run_vision2grasp_app import Vision2GraspApp


def snapshot(
    *,
    status: str = "FAILED",
    reason: str | None = "NO_CONTACT",
    result: dict[str, object] | None = None,
    state_history: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if result is None and status != "FAILED":
        result = {
            "state": status,
            "reason": reason,
            "state_machine_complete": True,
            "invalid_table_collision": False,
            "gripper_close_executed": True,
            "lift_height_m": 0.085,
            "stable_window_passed": True,
        }
    return {
        "status": status,
        "reason": reason,
        "request": {
            "simulation_attempt": {
                "attempt_id": "attempt-002",
                "target_id": "mug-01",
                "candidate_id": "candidate-07",
            }
        },
        "result": result,
        "telemetry": {"collision": reason == "COLLISION_ABORT"},
        "state_history": state_history or [
            {"state": "INITIALIZING", "elapsed_s": 0.0},
            {"state": "APPROACH", "elapsed_s": 0.2},
            {"state": "FAILED", "elapsed_s": 0.3},
        ],
    }


class ExecutionFeedbackTests(unittest.TestCase):
    def test_success_feedback_is_structured_and_machine_readable(self) -> None:
        feedback = build_grasp_execution_feedback(
            snapshot(status="SUCCESS", reason=None),
            task_id="task-001",
            event_id="feedback-001",
            execution_timestamp="2026-10-07T00:00:00Z",
        )
        document = feedback.public_metadata()
        self.assertEqual(feedback.message_type, "grasp_feedback")
        self.assertTrue(feedback.success)
        self.assertEqual(feedback.stage, "complete")
        self.assertIsNone(feedback.failure_type)
        self.assertEqual(document["task_id"], "task-001")
        self.assertEqual(document["attempt_id"], "attempt-002")
        self.assertEqual(feedback.chat_event()["message_type"], "grasp_feedback")

    def test_failure_taxonomy_reuses_existing_simulation_reasons(self) -> None:
        cases = {
            "COLLISION_ABORT": ("approach_collision", "approach"),
            "NO_CONTACT": ("miss_or_empty_closure", "contact"),
            "CONTACT_LOSS": ("slip_or_drop", "lift"),
            "SLIP": ("slip_or_drop", "lift"),
            "NO_LIFT": ("insufficient_contact", "lift"),
            "UNSTABLE_GRASP": ("unstable_grasp", "hold"),
        }
        for reason, (failure_type, stage) in cases.items():
            with self.subTest(reason=reason):
                result = {
                    "state": "FAILED",
                    "reason": reason,
                    "state_machine_complete": True,
                    "invalid_table_collision": reason == "COLLISION_ABORT",
                    "gripper_close_executed": True,
                    "lift_height_m": 0.02,
                    "stable_window_passed": reason == "UNSTABLE_GRASP",
                }
                feedback = build_grasp_execution_feedback(
                    snapshot(reason=reason, result=result),
                )
                self.assertFalse(feedback.success)
                self.assertEqual(feedback.failure_type, failure_type)
                self.assertEqual(feedback.stage, stage)
                self.assertEqual(feedback.source_failure_reason, reason)
                self.assertTrue(feedback.failure_evidence["state_history"])

    def test_missing_result_is_system_error_without_exposing_traceback(self) -> None:
        feedback = build_grasp_execution_feedback(
            snapshot(status="FAILED", reason="RuntimeError: driver stopped", result=None),
        )
        self.assertEqual(feedback.message_type, "system_error")
        self.assertEqual(feedback.failure_type, "unknown_failure")
        self.assertNotIn("RuntimeError", feedback.summary)
        self.assertEqual(feedback.source_failure_reason, "EXECUTION_ERROR")
        self.assertNotIn("RuntimeError", str(feedback.public_metadata()))
        self.assertIn("开发日志", feedback.failure_evidence["human_evidence_lines"][0])

    def test_unknown_execution_failure_stays_execution_feedback(self) -> None:
        result = {
            "state": "FAILED",
            "reason": "EXECUTION_ERROR",
            "state_machine_complete": False,
            "invalid_table_collision": False,
            "gripper_close_executed": False,
            "lift_height_m": 0.0,
            "stable_window_passed": False,
        }
        feedback = build_grasp_execution_feedback(snapshot(result=result, reason="EXECUTION_ERROR"))
        self.assertEqual(feedback.message_type, "grasp_feedback")
        self.assertEqual(feedback.failure_type, "unknown_failure")
        self.assertEqual(feedback.suggested_next_action, "inspect_system_status_before_retry")

    def test_chat_event_store_deduplicates_and_preserves_history(self) -> None:
        store = ChatEventStore(max_events=2)
        first = {"event_id": "one", "message_type": "grasp_feedback"}
        second = {"event_id": "two", "message_type": "grasp_feedback"}
        self.assertTrue(store.append_once(first))
        self.assertFalse(store.append_once(first))
        self.assertTrue(store.append_once(second))
        self.assertEqual(store.snapshot()["count"], 2)
        self.assertEqual(store.snapshot()["latest_event_id"], "two")

    def test_gongshu_app_bridges_terminal_snapshot_to_chat_event(self) -> None:
        class _LocalImage:
            @staticmethod
            def active_run_id() -> str:
                return "task-from-existing-run"

        app = object.__new__(Vision2GraspApp)
        app.chat_events = ChatEventStore()
        app.local_image = _LocalImage()
        terminal = snapshot(status="SUCCESS", reason=None)
        first = app._publish_execution_feedback(terminal, execution_token="exec-001")
        second = app._publish_execution_feedback(terminal, execution_token="exec-001")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(app.chat_events.snapshot()["count"], 1)
        event = app.chat_events.snapshot()["events"][0]
        self.assertEqual(event["message_type"], "grasp_feedback")
        self.assertEqual(event["metadata"]["task_id"], "task-from-existing-run")
        self.assertEqual(event["metadata"]["attempt_id"], "attempt-002")

    def test_frontend_polls_chat_event_and_renders_feedback_message_type(self) -> None:
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        source = (root / "frontend" / "apps" / "gongshu" / "assistant-workbench.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("/api/chat/events", source)
        self.assertIn('"grasp_feedback", "system_error"', source)
        self.assertIn('message.dataset.messageType = event.message_type', source)


if __name__ == "__main__":
    unittest.main()
