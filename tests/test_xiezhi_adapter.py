"""Integration tests for the optional Gongshu-owned Xiezhi adapter."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tomllib
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vision2grasp.contracts import GraspCandidate
from vision2grasp.extensions.xiezhi import (
    GongshuDecision,
    GongshuObservation,
    GongshuXiezhiAdapter,
    MayflowerXiezhiDecisionBackend,
    XiezhiAdapterConfig,
)


def observation() -> GongshuObservation:
    return GongshuObservation(
        episode_id="episode_1",
        observation_id="gongshu:observation:1",
        revision=0,
        timestamp_s=1.0,
        target_object_id="bottle",
        candidates=(GraspCandidate(
            "candidate_1",
            np.eye(4, dtype=np.float64),
            0.05,
            0.90,
            True,
        ),),
        position_std_m=0.01,
        rotation_std_rad=0.05,
        quality=0.90,
        occlusion=0.10,
    )


class FixedBackend:
    def decide(self, value: GongshuObservation) -> GongshuDecision:
        return GongshuDecision(
            "xiezhi_action_1",
            "ExecuteGrasp",
            candidate_id=value.candidates[0].candidate_id,
            parameters={"candidate_id": value.candidates[0].candidate_id},
            diagnostics={"reason": "integration_fixture"},
        )


class GongshuXiezhiAdapterTests(unittest.TestCase):
    def test_default_config_disables_xiezhi(self) -> None:
        with (ROOT / "configs" / "default.toml").open("rb") as handle:
            values = tomllib.load(handle)["gongshu_xiezhi"]
        config = XiezhiAdapterConfig.from_mapping(values)
        self.assertFalse(config.enabled)
        self.assertEqual(config.algorithm, "rule_based")

    def test_disabled_adapter_preserves_legacy_flow(self) -> None:
        calls: list[str] = []
        adapter = GongshuXiezhiAdapter(backend=FixedBackend())
        result = adapter.run(
            observation(),
            legacy_flow=lambda: calls.append("legacy") or "legacy_result",
            xiezhi_execution=lambda decision: calls.append("xiezhi"),
        )
        self.assertEqual(calls, ["legacy"])
        self.assertEqual(result.mode, "gongshu_legacy")
        self.assertEqual(result.execution, "legacy_result")
        self.assertIsNone(result.decision)

    def test_enabled_adapter_closes_observation_decision_execution_loop(self) -> None:
        calls: list[str] = []
        adapter = GongshuXiezhiAdapter(
            XiezhiAdapterConfig(enabled=True),
            FixedBackend(),
        )
        result = adapter.run(
            observation(),
            legacy_flow=lambda: calls.append("legacy"),
            xiezhi_execution=lambda decision: calls.append(decision.action_name or "stop")
            or {"executed": decision.candidate_id},
        )
        self.assertEqual(calls, ["ExecuteGrasp"])
        self.assertEqual(result.mode, "xiezhi")
        self.assertEqual(result.decision.candidate_id, "candidate_1")  # type: ignore[union-attr]
        self.assertEqual(result.execution, {"executed": "candidate_1"})

    @unittest.skipUnless(os.environ.get("XIEZHI_INTEGRATION_TEST") == "1",
                         "set XIEZHI_INTEGRATION_TEST=1 with Xiezhi on PYTHONPATH")
    def test_real_xiezhi_rule_policy_selects_gongshu_candidate(self) -> None:
        adapter = GongshuXiezhiAdapter(
            XiezhiAdapterConfig(enabled=True),
            MayflowerXiezhiDecisionBackend("rule_based"),
        )
        result = adapter.run(
            observation(),
            legacy_flow=lambda: self.fail("legacy flow must remain disabled"),
            xiezhi_execution=lambda decision: {"executed": decision.candidate_id},
        )
        self.assertEqual(result.decision.action_name, "ExecuteGrasp")  # type: ignore[union-attr]
        self.assertEqual(result.execution, {"executed": "candidate_1"})


if __name__ == "__main__":
    unittest.main()
