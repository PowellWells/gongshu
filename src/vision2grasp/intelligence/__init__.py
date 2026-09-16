"""Gongshu Intelligence Layer public surface."""

from .contracts import (
    AlgorithmDecision,
    AlgorithmObservation,
    CandidateEvidence,
    DecisionAction,
    DecisionStatus,
)
from .service import IntelligenceService
from .registry import AlgorithmRegistry, default_algorithm_registry
from .blueprint import (
    AlgorithmBlueprint,
    AlgorithmMetadata,
    AlgorithmStatus,
    AlgorithmType,
    BlueprintStage,
)
from .external_baseline import (
    EXTERNAL_BASELINE_PROVIDER_ID,
    MOCK_EXTERNAL_BASELINE_ID,
    MOCK_EXTERNAL_BASELINE_METADATA,
    ExternalAlgorithm,
    ExternalBaselineAdapter,
    ExternalBaselineInput,
    ExternalBaselineOutput,
    ExternalCandidateInput,
    MockExternalBaseline,
    MockSelectionStrategy,
    create_mock_external_baseline_provider,
)
from .arena import (
    AlgorithmArenaBackend,
    AlgorithmRun,
    ArenaAlgorithmReference,
    ArenaExperiment,
    ArenaExperimentStatus,
    ArenaResultStore,
    ResultRecord,
)

__all__ = [
    "AlgorithmDecision",
    "AlgorithmBlueprint",
    "AlgorithmMetadata",
    "AlgorithmStatus",
    "AlgorithmType",
    "AlgorithmRegistry",
    "AlgorithmObservation",
    "CandidateEvidence",
    "BlueprintStage",
    "DecisionAction",
    "DecisionStatus",
    "IntelligenceService",
    "EXTERNAL_BASELINE_PROVIDER_ID",
    "MOCK_EXTERNAL_BASELINE_ID",
    "MOCK_EXTERNAL_BASELINE_METADATA",
    "ExternalAlgorithm",
    "ExternalBaselineAdapter",
    "ExternalBaselineInput",
    "ExternalBaselineOutput",
    "ExternalCandidateInput",
    "MockExternalBaseline",
    "MockSelectionStrategy",
    "create_mock_external_baseline_provider",
    "AlgorithmArenaBackend",
    "AlgorithmRun",
    "ArenaAlgorithmReference",
    "ArenaExperiment",
    "ArenaExperimentStatus",
    "ArenaResultStore",
    "ResultRecord",
    "default_algorithm_registry",
]
