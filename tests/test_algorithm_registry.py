from __future__ import annotations

import unittest

from vision2grasp.intelligence import (
    AlgorithmMetadata,
    AlgorithmStatus,
    AlgorithmType,
)
from vision2grasp.intelligence.registry import (
    AlgorithmRegistry,
    default_algorithm_registry,
)


def metadata(
    algorithm_id: str,
    version: str,
    *,
    algorithm_type: AlgorithmType = AlgorithmType.XIEZHI_ALGORITHM,
    status: AlgorithmStatus = AlgorithmStatus.EXPERIMENTAL,
) -> AlgorithmMetadata:
    return AlgorithmMetadata(
        algorithm_id=algorithm_id,
        name="Xiezhi Decision",
        version=version,
        type=algorithm_type,
        description="Registry identity test algorithm.",
        status=status,
        source="test",
        created_time="2026-09-16T00:00:00+08:00",
        blueprint_reference=f"test.blueprint.{version}",
        provider_id="xiezhi",
        decision_contract="gongshu.intelligence-decision/v1",
        stages=("observation", "decision_output"),
        capabilities=("decision_selection",),
    )


class AlgorithmRegistryFormalizationTests(unittest.TestCase):
    def test_algorithm_types_and_statuses_are_closed_sets(self) -> None:
        self.assertEqual(
            {item.value for item in AlgorithmType},
            {"External Baseline", "Xiezhi Algorithm"},
        )
        self.assertEqual(
            {item.value for item in AlgorithmStatus},
            {"Prototype", "Experimental", "Validated", "Archived"},
        )

    def test_metadata_contains_the_required_identity_fields(self) -> None:
        public = metadata("xiezhi_decision_v0_1", "v0.1").public_metadata()
        self.assertTrue(
            {
                "algorithm_id",
                "name",
                "version",
                "type",
                "description",
                "status",
                "source",
                "created_time",
                "blueprint_reference",
            }.issubset(public)
        )

    def test_multiple_versions_coexist_and_are_queryable(self) -> None:
        registry = AlgorithmRegistry()
        version_01 = metadata("xiezhi_decision_v0_1", "v0.1")
        version_02 = metadata("xiezhi_decision_v0_2", "v0.2")
        registry.register_algorithm(version_01)
        registry.register_algorithm(version_02)

        self.assertIs(registry.query_algorithm("xiezhi_decision_v0_1"), version_01)
        self.assertIs(registry.get_by_name_version("Xiezhi Decision", "v0.2"), version_02)
        self.assertEqual(registry.list_algorithms(), (version_01, version_02))

    def test_registry_filters_by_type_and_status(self) -> None:
        registry = AlgorithmRegistry()
        xiezhi = metadata("xiezhi_decision_v0_1", "v0.1")
        external = AlgorithmMetadata(
            algorithm_id="external_reference_v1",
            name="External Reference",
            version="v1",
            type=AlgorithmType.EXTERNAL_BASELINE,
            description="Identity only; no provider integration.",
            status=AlgorithmStatus.ARCHIVED,
            source="external:test",
            created_time="2026-09-16T00:00:00+08:00",
            blueprint_reference="external.reference.v1",
            provider_id="external",
            decision_contract="gongshu.intelligence-decision/v1",
            stages=("observation", "decision_output"),
            capabilities=("decision_selection",),
        )
        registry.register_algorithm(xiezhi)
        registry.register_algorithm(external)

        self.assertEqual(
            registry.list_algorithms(algorithm_type=AlgorithmType.EXTERNAL_BASELINE),
            (external,),
        )
        self.assertEqual(
            registry.list_algorithms(status=AlgorithmStatus.EXPERIMENTAL),
            (xiezhi,),
        )

    def test_duplicate_id_or_name_version_is_rejected(self) -> None:
        registry = AlgorithmRegistry()
        registry.register_algorithm(metadata("xiezhi_decision_v0_1", "v0.1"))
        with self.assertRaisesRegex(ValueError, "algorithm ID"):
            registry.register_algorithm(metadata("xiezhi_decision_v0_1", "v0.2"))
        with self.assertRaisesRegex(ValueError, "name/version"):
            registry.register_algorithm(metadata("another_id", "v0.1"))

    def test_existing_xiezhi_v0_1_has_stable_identity_and_runtime_provider(self) -> None:
        registry = default_algorithm_registry(include_xiezhi=True)
        registered = registry.query_algorithm("xiezhi_decision_v0_1")
        self.assertIsNotNone(registered)
        assert registered is not None
        self.assertEqual(registered.name, "Xiezhi Decision")
        self.assertEqual(registered.version, "v0.1")
        self.assertIs(registered.type, AlgorithmType.XIEZHI_ALGORITHM)
        self.assertIs(registered.status, AlgorithmStatus.EXPERIMENTAL)
        provider = registry.create("xiezhi", "xiezhi_decision_v0_1")
        self.assertEqual(provider.algorithm_id, "xiezhi_decision_v0_1")


if __name__ == "__main__":
    unittest.main()
