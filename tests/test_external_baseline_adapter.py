from __future__ import annotations

import unittest

from test_intelligence_runtime import make_three_candidate_outcome
from vision2grasp.intelligence import (
    MOCK_EXTERNAL_BASELINE_ID,
    MOCK_EXTERNAL_BASELINE_METADATA,
    AlgorithmDecision,
    AlgorithmType,
    DecisionAction,
    IntelligenceService,
    create_mock_external_baseline_provider,
)
from vision2grasp.intelligence.registry import default_algorithm_registry


class ExternalBaselineAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_algorithm_registry(include_xiezhi=True)
        self.registry.register_algorithm(
            MOCK_EXTERNAL_BASELINE_METADATA,
            create_mock_external_baseline_provider,
        )

    def test_mock_external_baseline_can_register(self) -> None:
        self.assertTrue(
            self.registry.supports("external_baseline", MOCK_EXTERNAL_BASELINE_ID)
        )
        provider = self.registry.create(
            "external_baseline", MOCK_EXTERNAL_BASELINE_ID
        )
        self.assertEqual(provider.algorithm_id, MOCK_EXTERNAL_BASELINE_ID)

    def test_external_baseline_can_be_queried_with_complete_metadata(self) -> None:
        metadata = self.registry.query_algorithm(MOCK_EXTERNAL_BASELINE_ID)
        self.assertIs(metadata, MOCK_EXTERNAL_BASELINE_METADATA)
        assert metadata is not None
        self.assertIs(metadata.type, AlgorithmType.EXTERNAL_BASELINE)
        public = metadata.public_metadata()
        self.assertEqual(public["name"], "Mock External Baseline")
        self.assertEqual(public["version"], "v0.1")
        self.assertEqual(public["type"], "External Baseline")
        self.assertEqual(public["license"], "Test-Only")
        self.assertEqual(
            public["repository"], "mock://xiezhi/mock-external-baseline-v0.1"
        )

    def test_external_baseline_produces_algorithm_decision_v1(self) -> None:
        service = IntelligenceService(xiezhi_enabled=False, registry=self.registry)
        service.select_algorithm("external_baseline", MOCK_EXTERNAL_BASELINE_ID)
        decision = service.decide(make_three_candidate_outcome())

        self.assertIsInstance(decision, AlgorithmDecision)
        self.assertEqual(decision.action, DecisionAction.EXECUTE_GRASP)
        self.assertEqual(decision.selected_candidate_id, "C3")
        self.assertEqual(decision.provider_id, "external_baseline")
        self.assertEqual(decision.algorithm_id, MOCK_EXTERNAL_BASELINE_ID)
        self.assertEqual(
            decision.public_metadata()["schema_version"],
            "gongshu.intelligence-decision/v1",
        )
        self.assertEqual(
            decision.diagnostics["adapter"], "ExternalBaselineAdapter"
        )

    def test_mock_strategy_is_recorded_without_runtime_control(self) -> None:
        service = IntelligenceService(xiezhi_enabled=False, registry=self.registry)
        service.select_algorithm("external_baseline", MOCK_EXTERNAL_BASELINE_ID)
        decision = service.decide(make_three_candidate_outcome())
        self.assertEqual(decision.diagnostics["strategy"], "lowest_score")
        self.assertNotIn("robot", decision.diagnostics)
        self.assertNotIn("mujoco", decision.diagnostics)

    def test_xiezhi_decision_v0_1_is_unchanged(self) -> None:
        decision = IntelligenceService(
            xiezhi_enabled=True,
            registry=self.registry,
        ).decide(make_three_candidate_outcome())
        self.assertEqual(decision.provider_id, "xiezhi")
        self.assertEqual(decision.algorithm_id, "xiezhi_decision_v0_1")
        self.assertEqual(decision.action, DecisionAction.EXECUTE_GRASP)


if __name__ == "__main__":
    unittest.main()
