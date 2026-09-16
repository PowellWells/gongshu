from __future__ import annotations

import unittest

from test_algorithm_arena import arena_observation
from vision2grasp.intelligence import (
    MOCK_EXTERNAL_BASELINE_ID,
    MOCK_EXTERNAL_BASELINE_METADATA,
    AlgorithmArenaBackend,
    AlgorithmArenaRunner,
    ArenaExperimentStatus,
    MockArenaValidation,
    create_mock_external_baseline_provider,
)
from vision2grasp.intelligence.registry import default_algorithm_registry


class AlgorithmArenaRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        registry = default_algorithm_registry(include_xiezhi=True)
        registry.register_algorithm(
            MOCK_EXTERNAL_BASELINE_METADATA,
            create_mock_external_baseline_provider,
        )
        self.backend = AlgorithmArenaBackend(registry)
        self.xiezhi = self.backend.algorithm_reference("xiezhi_decision_v0_1")
        self.external = self.backend.algorithm_reference(MOCK_EXTERNAL_BASELINE_ID)
        self.validation_environment_id = "mock-validation-fixed-01"
        self.observation = arena_observation()

    def experiment(self, algorithms):
        return self.backend.create_experiment(
            experiment_id="arena-runner-experiment-01",
            scene_id="scene-fixed-01",
            candidate_pool_id="candidate-pool-fixed-01",
            algorithms=tuple(algorithms),
            validation_environment_id=self.validation_environment_id,
        )

    def runner(self) -> AlgorithmArenaRunner:
        return AlgorithmArenaRunner(
            self.backend,
            MockArenaValidation(self.validation_environment_id),
        )

    def test_single_algorithm_experiment_runs(self) -> None:
        runner = self.runner()
        execution = runner.run(self.experiment((self.xiezhi,)), self.observation)

        self.assertEqual(execution.status, ArenaExperimentStatus.COMPLETED)
        self.assertEqual(len(execution.algorithm_runs), 1)
        self.assertEqual(execution.algorithm_runs[0].algorithm_id, "xiezhi_decision_v0_1")
        self.assertEqual(runner.run_store.list(), execution.algorithm_runs)

    def test_multiple_algorithm_experiment_runs_sequentially(self) -> None:
        runner = self.runner()
        execution = runner.run(
            self.experiment((self.xiezhi, self.external)),
            self.observation,
        )

        self.assertEqual(
            [run.algorithm_id for run in execution.algorithm_runs],
            ["xiezhi_decision_v0_1", MOCK_EXTERNAL_BASELINE_ID],
        )
        self.assertEqual(len(execution.result_records), 2)

    def test_xiezhi_and_mock_external_share_one_experiment_only(self) -> None:
        experiment = self.experiment((self.xiezhi, self.external))
        execution = self.runner().run(experiment, self.observation)

        self.assertEqual(
            {run.experiment_id for run in execution.algorithm_runs},
            {experiment.experiment_id},
        )
        self.assertEqual(
            {run.input_reference for run in execution.algorithm_runs},
            {experiment.candidate_pool_id},
        )

    def test_each_algorithm_generates_an_independent_run_and_decision(self) -> None:
        execution = self.runner().run(
            self.experiment((self.xiezhi, self.external)),
            self.observation,
        )
        first, second = execution.algorithm_runs

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertIsNot(first.decision_output, second.decision_output)
        self.assertNotEqual(
            first.decision_output.decision_id,
            second.decision_output.decision_id,
        )

    def test_result_records_are_saved_with_validation_outcomes(self) -> None:
        runner = self.runner()
        execution = runner.run(
            self.experiment((self.xiezhi, self.external)),
            self.observation,
        )

        self.assertEqual(runner.result_store.list(), execution.result_records)
        for run, result in zip(
            execution.algorithm_runs,
            execution.result_records,
            strict=True,
        ):
            self.assertTrue(result.success)
            self.assertIsNone(result.failure_reason)
            self.assertEqual(result.algorithm_run_id, run.run_id)
            self.assertEqual(result.validation_result["status"], "SUCCESS")
            self.assertEqual(result.execution_time, 0.0)

    def test_runner_does_not_create_candidates_or_runtime_controls(self) -> None:
        execution = self.runner().run(
            self.experiment((self.xiezhi, self.external)),
            self.observation,
        )
        for result in execution.result_records:
            self.assertEqual(
                result.metadata["candidate_pool_id"],
                "candidate-pool-fixed-01",
            )
            self.assertNotIn("robot", result.validation_result)
            self.assertNotIn("mujoco", result.validation_result)


if __name__ == "__main__":
    unittest.main()
