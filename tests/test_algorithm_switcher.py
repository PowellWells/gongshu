from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from test_intelligence_runtime import make_three_candidate_outcome
from vision2grasp.intelligence import (
    MOCK_EXTERNAL_BASELINE_ID,
    ActiveAlgorithmSelector,
    AlgorithmDecision,
    AlgorithmLoader,
    DecisionEngine,
    IntelligenceService,
    default_algorithm_registry,
)


class AlgorithmSwitcherV1Tests(unittest.TestCase):
    def test_default_active_algorithm_is_xiezhi_decision_v0_1(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)

        active = service.active_algorithm()

        self.assertEqual(active.algorithm_id, "xiezhi_decision_v0_1")
        self.assertEqual(active.name, "Xiezhi Decision")
        self.assertEqual(active.version, "v0.1")

    def test_loader_resolves_providers_from_algorithm_id(self) -> None:
        registry = default_algorithm_registry(
            include_xiezhi=True,
            include_mock_external=True,
        )
        loader = AlgorithmLoader(registry)

        xiezhi = loader.load("xiezhi_decision_v0_1")
        external = loader.load(MOCK_EXTERNAL_BASELINE_ID)

        self.assertEqual(xiezhi.provider_id, "xiezhi")
        self.assertEqual(external.provider_id, "external_baseline")

    def test_decision_engine_uses_active_selector_and_loader(self) -> None:
        registry = default_algorithm_registry(
            include_xiezhi=True,
            include_mock_external=True,
        )
        selector = ActiveAlgorithmSelector(registry, "xiezhi_decision_v0_1")
        engine = DecisionEngine(selector, AlgorithmLoader(registry))
        observation = IntelligenceService(xiezhi_enabled=True)._observation(
            make_three_candidate_outcome()
        )

        selector.set_active_algorithm(MOCK_EXTERNAL_BASELINE_ID)
        decision = engine.decide(observation)

        self.assertEqual(decision.algorithm_id, MOCK_EXTERNAL_BASELINE_ID)

    def test_unified_input_exposes_candidate_pool_and_robot_state(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)
        observation = service._observation(make_three_candidate_outcome())

        self.assertIs(observation.candidate_pool, observation.candidates)
        self.assertEqual(dict(observation.robot_state), {})

    def test_switch_changes_decision_output_without_runtime_call_changes(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)
        outcome = make_three_candidate_outcome()

        xiezhi_decision = service.decide(outcome)
        active = service.set_active_algorithm(MOCK_EXTERNAL_BASELINE_ID)
        external_decision = service.decide(outcome)

        self.assertEqual(active.name, "Mock External Baseline")
        self.assertIsInstance(xiezhi_decision, AlgorithmDecision)
        self.assertIsInstance(external_decision, AlgorithmDecision)
        self.assertEqual(xiezhi_decision.algorithm_id, "xiezhi_decision_v0_1")
        self.assertEqual(external_decision.algorithm_id, MOCK_EXTERNAL_BASELINE_ID)
        self.assertEqual(external_decision.provider_id, "external_baseline")
        self.assertEqual(xiezhi_decision.selected_candidate_id, "C1")
        self.assertEqual(external_decision.selected_candidate_id, "C3")
        self.assertEqual(external_decision.reason, "mock_lowest_score")

    def test_active_algorithm_state_can_be_persisted_and_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_path = Path(temporary) / "active-algorithm.json"
            registry = default_algorithm_registry(
                include_xiezhi=True,
                include_mock_external=True,
            )
            selector = ActiveAlgorithmSelector(
                registry,
                "xiezhi_decision_v0_1",
                state_path=state_path,
            )
            selector.set_active_algorithm(MOCK_EXTERNAL_BASELINE_ID)

            restored = ActiveAlgorithmSelector(
                registry,
                "xiezhi_decision_v0_1",
                state_path=state_path,
            )

            self.assertTrue(state_path.is_file())
            self.assertEqual(
                restored.get_active_algorithm().algorithm_id,
                MOCK_EXTERNAL_BASELINE_ID,
            )

    def test_dashboard_reads_active_algorithm_identity(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)
        service.set_active_algorithm(MOCK_EXTERNAL_BASELINE_ID)
        service.decide(make_three_candidate_outcome())

        dashboard = service.dashboard_state()

        self.assertIsNotNone(dashboard)
        assert dashboard is not None
        active = dashboard.public_metadata()["active_algorithm"]
        self.assertEqual(active["name"], "Mock External Baseline")
        self.assertEqual(active["version"], "v0.1")
        self.assertEqual(active["type"], "External Baseline")
        self.assertEqual(active["status"], "Prototype")

    def test_compatibility_selector_uses_the_same_active_state(self) -> None:
        service = IntelligenceService(xiezhi_enabled=True)

        state = service.select_algorithm(
            "external_baseline",
            MOCK_EXTERNAL_BASELINE_ID,
        )

        self.assertEqual(state["selected_algorithm"], MOCK_EXTERNAL_BASELINE_ID)
        self.assertEqual(
            state["active_algorithm"]["algorithm_id"],
            MOCK_EXTERNAL_BASELINE_ID,
        )


if __name__ == "__main__":
    unittest.main()
