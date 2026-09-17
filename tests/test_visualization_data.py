from __future__ import annotations

import json
import unittest

from test_algorithm_arena import arena_observation
from vision2grasp.intelligence import (
    MOCK_EXTERNAL_BASELINE_ID,
    MOCK_EXTERNAL_BASELINE_METADATA,
    AlgorithmArenaBackend,
    AlgorithmArenaRunner,
    MockArenaValidation,
    VisualizationDataProvider,
    XiezhiDashboardState,
    create_mock_external_baseline_provider,
)
from vision2grasp.intelligence.registry import default_algorithm_registry


class VisualizationDataProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_algorithm_registry(include_xiezhi=True)
        self.registry.register_algorithm(
            MOCK_EXTERNAL_BASELINE_METADATA,
            create_mock_external_baseline_provider,
        )
        backend = AlgorithmArenaBackend(self.registry)
        xiezhi = backend.algorithm_reference("xiezhi_decision_v0_1")
        external = backend.algorithm_reference(MOCK_EXTERNAL_BASELINE_ID)
        experiment = backend.create_experiment(
            experiment_id="visualization-experiment-01",
            scene_id="scene-fixed-01",
            candidate_pool_id="candidate-pool-fixed-01",
            algorithms=(xiezhi, external),
            validation_environment_id="mock-validation-fixed-01",
        )
        runner = AlgorithmArenaRunner(
            backend,
            MockArenaValidation("mock-validation-fixed-01"),
        )
        self.execution = runner.run(experiment, arena_observation())
        self.state = VisualizationDataProvider(self.registry).build(
            self.execution.algorithm_runs[0].decision_output,
            self.execution.result_records,
        )

    def test_dashboard_state_can_be_generated_and_serialized(self) -> None:
        self.assertIsInstance(self.state, XiezhiDashboardState)
        payload = self.state.public_metadata()
        self.assertEqual(payload["schema_version"], "gongshu.xiezhi-dashboard/v1")
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "active_algorithm",
                "runtime",
                "engine",
                "evidence",
                "history",
            },
        )
        self.assertEqual(json.loads(json.dumps(payload))["runtime"]["current_action"], "EXECUTE_GRASP")

    def test_runtime_view_uses_algorithm_decision_v1(self) -> None:
        runtime = self.state.runtime
        decision = self.execution.algorithm_runs[0].decision_output
        self.assertEqual(runtime.current_algorithm, "Xiezhi Decision")
        self.assertEqual(runtime.algorithm_version, "v0.1")
        self.assertEqual(runtime.current_action, decision.action.value)
        self.assertEqual(runtime.selected_candidate, decision.selected_candidate_id)
        self.assertEqual(runtime.confidence, decision.confidence)
        self.assertEqual(runtime.risk, decision.risk_estimation)
        self.assertEqual(runtime.reason, decision.reason)

    def test_engine_view_uses_registry_metadata(self) -> None:
        engine = self.state.engine
        registered = self.registry.query_algorithm("xiezhi_decision_v0_1")
        assert registered is not None
        self.assertEqual(engine.algorithm_metadata, registered.public_metadata())
        self.assertEqual(engine.algorithm_type, "Xiezhi Algorithm")
        self.assertEqual(engine.algorithm_version, "v0.1")
        self.assertEqual(engine.algorithm_status, "Experimental")
        self.assertEqual(engine.blueprint_reference, "xiezhi.decision.v0_1")

    def test_active_algorithm_exposes_switcher_identity(self) -> None:
        active = self.state.active_algorithm.public_metadata()
        self.assertEqual(active["name"], "Xiezhi Decision")
        self.assertEqual(active["version"], "v0.1")
        self.assertEqual(active["type"], "Xiezhi Algorithm")
        self.assertEqual(active["status"], "Experimental")

    def test_arena_history_uses_result_records(self) -> None:
        self.assertEqual(len(self.state.history), 2)
        first, second = self.state.history
        self.assertEqual(first.experiment_id, "visualization-experiment-01")
        self.assertEqual(first.algorithm["algorithm_id"], "xiezhi_decision_v0_1")
        self.assertEqual(second.algorithm["algorithm_id"], MOCK_EXTERNAL_BASELINE_ID)
        self.assertTrue(first.success)
        self.assertEqual(first.validation_result["status"], "SUCCESS")
        self.assertEqual(
            first.timestamp,
            self.execution.result_records[0].created_time,
        )

    def test_blueprint_information_is_readable_from_registry(self) -> None:
        blueprint = self.state.engine.blueprint
        self.assertIsNotNone(blueprint)
        assert blueprint is not None
        self.assertEqual(blueprint["blueprint_id"], "xiezhi.decision.v0_1")
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
        candidate_evaluation = blueprint["stages"][1]
        self.assertEqual(candidate_evaluation["module"], "decision_v0_1.py")
        self.assertEqual(candidate_evaluation["function"], "evaluate_candidates()")

    def test_evidence_view_uses_current_decision_output(self) -> None:
        decision = self.execution.algorithm_runs[0].decision_output
        evidence = self.state.evidence
        self.assertEqual(evidence.selected_candidate, decision.selected_candidate_id)
        self.assertEqual(evidence.risk_information["value"], decision.risk_estimation)
        self.assertEqual(
            evidence.uncertainty_information["items"],
            list(decision.uncertainty),
        )
        self.assertEqual(evidence.diagnostics, decision.diagnostics)


if __name__ == "__main__":
    unittest.main()
