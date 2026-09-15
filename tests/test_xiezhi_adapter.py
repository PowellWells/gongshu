"""Integration tests for Gongshu-to-Xiezhi lifecycle state exchange."""

from __future__ import annotations

from functools import partial
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import tomllib
import unittest
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision2grasp.extensions.xiezhi.lifecycle import (
    GongshuRuntimeContext,
    GongshuXiezhiLifecycleAdapter,
)
from run_vision2grasp_app import AppRequestHandler, Vision2GraspApp


class FakeStatus:
    def __init__(self, event: str | None, count: int, context=None) -> None:
        self.event = event
        self.count = count
        self.context = context

    def as_dict(self):
        return {
            "module": "xiezhi",
            "status": "ready",
            "connected": True,
            "last_event": self.event,
            "last_timestamp": 5.0 if self.event else None,
            "event_count": self.count,
            "context": self.context,
        }


class FakeLifecycleRuntime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def receive_event(self, event, context, *, timestamp=None):
        self.events.append((event, dict(context)))
        return FakeStatus(event, len(self.events), dict(context))

    def status(self):
        if not self.events:
            return FakeStatus(None, 0)
        event, context = self.events[-1]
        return FakeStatus(event, len(self.events), context)


class FinishedMuJoCoSnapshot:
    def snapshot(self):
        return {
            "state": "SUCCESS",
            "state_history": [
                {"state": "INITIALIZING"},
                {"state": "APPROACH"},
                {"state": "SUCCESS"},
            ],
        }


class BrokenLifecycleRuntime:
    def receive_event(self, event, context, *, timestamp=None):
        raise RuntimeError("optional runtime failed")

    def status(self):
        return FakeStatus(None, 0)


def context(status: str = "running") -> GongshuRuntimeContext:
    return GongshuRuntimeContext(
        robot="panda",
        simulation="mujoco",
        scene="bottle_lift",
        task="grasp_test",
        status=status,
    )


class GongshuXiezhiLifecycleTests(unittest.TestCase):
    def test_lifecycle_import_does_not_load_decision_backend_or_rule_policy(self) -> None:
        pythonpath = os.pathsep.join(filter(None, (
            str(ROOT / "src"),
            os.environ.get("PYTHONPATH", ""),
        )))
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "from vision2grasp.extensions.xiezhi.lifecycle import "
                    "GongshuXiezhiLifecycleAdapter; "
                    "assert 'vision2grasp.extensions.xiezhi.backend' not in sys.modules; "
                    "assert 'grasp_decision.policies.rule_based' not in sys.modules"
                ),
            ],
            env={**os.environ, "PYTHONPATH": pythonpath},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_default_config_enables_lifecycle_without_algorithm_setting(self) -> None:
        with (ROOT / "configs" / "default.toml").open("rb") as handle:
            values = tomllib.load(handle)["gongshu_xiezhi"]
        self.assertEqual(values, {"enabled": True})

    def test_event_reaches_runtime_and_status_returns_to_gongshu(self) -> None:
        runtime = FakeLifecycleRuntime()
        adapter = GongshuXiezhiLifecycleAdapter(runtime=runtime)
        status = adapter.publish("episode_start", context(), timestamp=5.0)
        self.assertEqual(runtime.events[0][0], "episode_start")
        self.assertEqual(runtime.events[0][1]["source"], "gongshu")
        self.assertEqual(runtime.events[0][1]["simulation"], "mujoco")
        self.assertTrue(status.connected)
        self.assertEqual(status.last_event, "episode_start")
        self.assertEqual(status.event_count, 1)

    def test_disabled_or_missing_xiezhi_never_blocks_gongshu(self) -> None:
        disabled = GongshuXiezhiLifecycleAdapter(enabled=False)
        unavailable = GongshuXiezhiLifecycleAdapter(enabled=True)
        self.assertEqual(disabled.publish("episode_start", context()).status, "disabled")
        self.assertFalse(unavailable.publish("episode_start", context()).connected)

    def test_runtime_failure_degrades_to_unavailable_without_escaping(self) -> None:
        adapter = GongshuXiezhiLifecycleAdapter(runtime=BrokenLifecycleRuntime())
        status = adapter.publish("episode_start", context())
        self.assertEqual(status.status, "unavailable")
        self.assertFalse(status.connected)

    def test_status_feedback_is_available_over_gongshu_http(self) -> None:
        runtime = FakeLifecycleRuntime()
        adapter = GongshuXiezhiLifecycleAdapter(runtime=runtime)
        adapter.publish("episode_start", context(), timestamp=5.0)
        app = type("StatusApp", (), {"xiezhi": adapter})()
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(AppRequestHandler, app=app),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(
                f"http://127.0.0.1:{server.server_address[1]}/api/xiezhi/status",
                timeout=2,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertTrue(payload["connected"])
            self.assertEqual(payload["last_event"], "episode_start")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_mujoco_snapshot_relay_emits_finish_and_episode_end(self) -> None:
        runtime = FakeLifecycleRuntime()
        app = object.__new__(Vision2GraspApp)
        app.xiezhi = GongshuXiezhiLifecycleAdapter(runtime=runtime)
        app.mujoco_validation = FinishedMuJoCoSnapshot()
        app._xiezhi_watch_lock = threading.Lock()
        app._xiezhi_watch_generation = 1
        app.xiezhi.publish("simulation_start", context("ready"))
        app.xiezhi.publish("episode_start", context("running"))

        app._watch_xiezhi_lifecycle(1, "bottle_lift")

        events = [event for event, _ in runtime.events]
        self.assertEqual(events[:2], ["simulation_start", "episode_start"])
        self.assertEqual(events.count("step_update"), 3)
        self.assertEqual(events[-2:], ["execution_finish", "episode_end"])
        self.assertEqual(runtime.events[-1][1]["result"], "success")

    @unittest.skipUnless(
        os.environ.get("XIEZHI_INTEGRATION_TEST") == "1",
        "set XIEZHI_INTEGRATION_TEST=1 with Xiezhi on PYTHONPATH",
    )
    def test_real_xiezhi_runtime_records_lifecycle_without_policy(self) -> None:
        adapter = GongshuXiezhiLifecycleAdapter.connect(enabled=True)
        self.assertTrue(adapter.status().connected)
        for event in (
            "simulation_start",
            "episode_start",
            "step_update",
            "execution_finish",
            "episode_end",
        ):
            status = adapter.publish(event, context(event), result=(
                "success" if event in {"execution_finish", "episode_end"} else None
            ))
        self.assertEqual(status.last_event, "episode_end")
        self.assertEqual(status.event_count, 5)
        self.assertEqual(status.context["result"], "success")


if __name__ == "__main__":
    unittest.main()
