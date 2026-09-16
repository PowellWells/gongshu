from __future__ import annotations

import json
import unittest

from test_intelligence_runtime import make_three_candidate_outcome
from vision2grasp.intelligence import (
    MOCK_EXTERNAL_BASELINE_ID,
    MOCK_EXTERNAL_BASELINE_METADATA,
    AlgorithmArenaBackend,
    AlgorithmDecision,
    AlgorithmObservation,
    ArenaResultStore,
    CandidateEvidence,
    create_mock_external_baseline_provider,
)
from vision2grasp.intelligence.registry import default_algorithm_registry


def arena_observation() -> AlgorithmObservation:
    outcome = make_three_candidate_outcome()
    assert outcome.plan is not None
    return AlgorithmObservation(
        observation_id="arena-observation-01",
        episode_id="arena-episode-01",
        revision=0,
        timestamp_s=1.0,
        target_id=outcome.plan.target_id,
        candidates=tuple(
            CandidateEvidence(
                candidate_id=candidate.candidate_id,
                target_id=candidate.target_instance_id,
                grasp_point_xyz=candidate.grasp_point_xyz,
                approach_vector=candidate.approach_vector,
                closing_vector=candidate.closing_vector,
                gripper_width_m=candidate.gripper_width,
                score=candidate.ranking_score,
                executable=candidate.executable,
                score_factors=candidate.score_factors,
            )
            for candidate in outcome.candidates
        ),
        best_candidate_id=outcome.plan.best_candidate_id,
        evidence_confidence=outcome.plan.confidence.value,
        reliability="RELIABLE",
    )


class AlgorithmArenaBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        registry = default_algorithm_registry(include_xiezhi=True)
        registry.register_algorithm(
            MOCK_EXTERNAL_BASELINE_METADATA,
            create_mock_external_baseline_provider,
        )
        self.backend = AlgorithmArenaBackend(registry)
        self.xiezhi = self.backend.algorithm_reference("xiezhi_decision_v0_1")
        self.external = self.backend.algorithm_reference(MOCK_EXTERNAL_BASELINE_ID)
        self.experiment = self.backend.create_experiment(
            experiment_id="arena-experiment-01",
            scene_id="scene-fixed-01",
            candidate_pool_id="candidate-pool-fixed-01",
            algorithms=(self.xiezhi, self.external),
            validation_environment_id="validation-fixed-01",
        )
        self.observation = arena_observation()

    def test_xiezhi_decision_v0_1_can_enter_arena(self) -> None:
        run = self.backend.run_algorithm(
            self.experiment,
            self.xiezhi,
            self.observation,
            input_reference="candidate-pool-fixed-01",
        )
        self.assertEqual(run.algorithm_id, "xiezhi_decision_v0_1")
        self.assertEqual(run.algorithm_version, "v0.1")
        self.assertIsInstance(run.decision_output, AlgorithmDecision)

    def test_mock_external_baseline_can_enter_arena(self) -> None:
        run = self.backend.run_algorithm(
            self.experiment,
            self.external,
            self.observation,
            input_reference="candidate-pool-fixed-01",
        )
        self.assertEqual(run.algorithm_id, MOCK_EXTERNAL_BASELINE_ID)
        self.assertEqual(run.algorithm_version, "v0.1")
        self.assertIsInstance(run.decision_output, AlgorithmDecision)

    def test_algorithms_produce_distinct_runs_under_fixed_conditions(self) -> None:
        xiezhi_run = self.backend.run_algorithm(
            self.experiment,
            self.xiezhi,
            self.observation,
            input_reference="candidate-pool-fixed-01",
        )
        external_run = self.backend.run_algorithm(
            self.experiment,
            self.external,
            self.observation,
            input_reference="candidate-pool-fixed-01",
        )
        self.assertNotEqual(xiezhi_run.run_id, external_run.run_id)
        self.assertNotEqual(xiezhi_run.algorithm_id, external_run.algorithm_id)
        self.assertEqual(xiezhi_run.input_reference, external_run.input_reference)
        self.assertEqual(xiezhi_run.experiment_id, external_run.experiment_id)

    def test_result_record_can_be_saved_and_serialized(self) -> None:
        run = self.backend.run_algorithm(
            self.experiment,
            self.xiezhi,
            self.observation,
            input_reference="candidate-pool-fixed-01",
        )
        record = self.backend.record_result(
            run,
            success=True,
            failure_reason=None,
            validation_result={"status": "SUCCESS", "candidate_id": "C1"},
            execution_time=0.42,
            metadata={"scene_id": self.experiment.scene_id},
        )
        store = ArenaResultStore()
        saved = store.save(record)

        self.assertIs(store.get(record.record_id), saved)
        self.assertEqual(store.list(), (record,))
        self.assertEqual(record.algorithm_run_id, run.run_id)
        payload = record.public_metadata()
        self.assertEqual(json.loads(json.dumps(payload))["success"], True)

    def test_experiment_freezes_scene_pool_and_validation_environment(self) -> None:
        payload = self.experiment.public_metadata()
        self.assertEqual(payload["scene_id"], "scene-fixed-01")
        self.assertEqual(payload["candidate_pool_id"], "candidate-pool-fixed-01")
        self.assertEqual(payload["validation_environment_id"], "validation-fixed-01")
        self.assertEqual(len(payload["algorithms"]), 2)
        with self.assertRaisesRegex(ValueError, "fixed candidate pool"):
            self.backend.run_algorithm(
                self.experiment,
                self.xiezhi,
                self.observation,
                input_reference="different-candidate-pool",
            )


if __name__ == "__main__":
    unittest.main()
