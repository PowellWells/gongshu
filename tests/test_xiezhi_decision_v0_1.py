from __future__ import annotations

import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from test_intelligence_runtime import make_outcome
from vision2grasp.extensions.xiezhi.algorithms import (
    XIEZHI_DECISION_V0_1_BLUEPRINT,
    XIEZHI_DECISION_V0_1_ID,
)
from vision2grasp.intelligence import DecisionAction, IntelligenceService
from vision2grasp.intelligence.registry import default_algorithm_registry


class XiezhiDecisionV01Tests(unittest.TestCase):
    def test_blueprint_freezes_the_five_stage_algorithm_structure(self) -> None:
        blueprint = XIEZHI_DECISION_V0_1_BLUEPRINT.public_metadata()
        self.assertEqual(blueprint["schema_version"], "gongshu.algorithm-blueprint/v1")
        self.assertEqual(blueprint["algorithm"], XIEZHI_DECISION_V0_1_ID)
        self.assertEqual(
            [stage["stage_id"] for stage in blueprint["stages"]],
            [
                "observation",
                "candidate_evaluation",
                "risk_assessment",
                "decision_selection",
                "decision_output",
            ],
        )
        self.assertEqual(
            blueprint["edges"],
            [
                ["observation", "candidate_evaluation"],
                ["candidate_evaluation", "risk_assessment"],
                ["risk_assessment", "decision_selection"],
                ["decision_selection", "decision_output"],
            ],
        )

    def test_registry_exposes_versioned_algorithm_metadata(self) -> None:
        registry = default_algorithm_registry(include_xiezhi=True)
        metadata = registry.metadata("xiezhi", XIEZHI_DECISION_V0_1_ID)
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata["name"], "Xiezhi Decision")
        self.assertEqual(metadata["version"], "v0.1")
        self.assertEqual(metadata["type"], "Xiezhi Algorithm")
        self.assertEqual(metadata["status"], "Experimental")
        self.assertEqual(metadata["decision_contract"], "gongshu.intelligence-decision/v1")
        self.assertEqual(metadata["blueprint_schema_version"], "gongshu.algorithm-blueprint/v1")

    def test_decision_diagnostics_preserve_each_formal_stage_result(self) -> None:
        decision = IntelligenceService(xiezhi_enabled=True).decide(make_outcome())
        self.assertEqual(decision.action, DecisionAction.EXECUTE_GRASP)
        self.assertEqual(decision.algorithm_id, XIEZHI_DECISION_V0_1_ID)
        self.assertEqual(
            decision.diagnostics["pipeline_stages"],
            [
                "observation",
                "candidate_evaluation",
                "risk_assessment",
                "decision_selection",
                "decision_output",
            ],
        )
        self.assertEqual(
            decision.diagnostics["candidate_evaluations"][0]["candidate_id"],
            "candidate-01",
        )
        self.assertTrue(decision.diagnostics["risk_assessment"]["acceptable"])
        self.assertEqual(
            decision.diagnostics["decision_selection"]["selected_candidate_id"],
            "candidate-01",
        )

    def test_low_scoring_candidate_requests_reobservation(self) -> None:
        decision = IntelligenceService(xiezhi_enabled=True).decide(
            make_outcome(score=0.50)
        )
        self.assertEqual(decision.action, DecisionAction.REOBSERVE)
        self.assertIsNone(decision.selected_candidate_id)
        self.assertIn("CANDIDATE_SCORE_LOW", decision.uncertainty)
        self.assertFalse(decision.authorizes_execution)


if __name__ == "__main__":
    unittest.main()
