import asyncio
import json

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from packet_support import (
    NOW,
    REPOSITORY_ROOT,
    MemoryManifestRepository,
    RecordingArtifactWriter,
    load_generation_request,
)
from veritas_runtime.packets.generator import (
    DecisionPacketGenerator,
    IdempotencyConflict,
    PacketGenerationError,
)
from veritas_runtime.packets.models import ArtifactBlueprint, ArtifactKind, ArtifactMutability


def test_canonical_packet_is_generated_from_sources_with_writer_owned_anchors() -> None:
    request_id, blueprint, sources = load_generation_request()
    writer = RecordingArtifactWriter()
    manifests = MemoryManifestRepository()

    async def scenario() -> None:
        generated = await DecisionPacketGenerator(writer, manifests).generate(
            request_id, blueprint, sources, NOW
        )
        assert generated.reused is False
        assert len(writer.calls) == 5
        assert len(generated.manifest.claims) == 8

        actual = generated.manifest.model_dump(mode="json", by_alias=True)
        schema = json.loads((REPOSITORY_ROOT / "schemas/claim-manifest.schema.json").read_text())
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(actual)

        expected = json.loads(
            (REPOSITORY_ROOT / "fixtures/demo/q3-executive-review.json").read_text()
        )
        expected_statements = {claim["claimId"]: claim["statement"] for claim in expected["claims"]}
        actual_statements = {claim["claimId"]: claim["statement"] for claim in actual["claims"]}
        assert actual_statements == expected_statements
        assert all(
            anchor["anchor"].startswith("workspace://")
            for claim in actual["claims"]
            for anchor in claim["artifactAnchors"]
        )
        assert all(
            set(source) == {"sourceId", "kind", "resourceId", "anchor", "version"}
            for source in actual["sources"]
        )

    asyncio.run(scenario())


def test_generation_is_idempotent_and_changed_sources_create_a_new_version() -> None:
    request_id, blueprint, sources = load_generation_request()
    writer = RecordingArtifactWriter()
    manifests = MemoryManifestRepository()
    generator = DecisionPacketGenerator(writer, manifests)

    async def scenario() -> None:
        original = await generator.generate(request_id, blueprint, sources, NOW)
        replay = await generator.generate(request_id, blueprint, sources, NOW)
        assert replay.reused is True
        assert replay.manifest == original.manifest
        assert len(writer.calls) == 5

        changed_sources = tuple(
            source.model_copy(update={"value": 0.09}) if source.source_id == "src-churn" else source
            for source in sources
        )
        with pytest.raises(IdempotencyConflict, match="different inputs"):
            await generator.generate(request_id, blueprint, changed_sources, NOW)

        changed = await generator.generate("changed-q3-input", blueprint, changed_sources, NOW)
        statements = {claim.claim_id: claim.statement for claim in changed.manifest.claims}
        assert changed.manifest.version == 2
        assert statements["claim-churn-value"] == "Q3 customer churn is 9%."
        assert statements["claim-churn-improved"] == "Customer churn worsened during Q3."
        assert statements["claim-retention-target"] == (
            "The retention target has not been achieved."
        )
        assert statements["claim-scale-acquisition"] == (
            "The company should pause the planned increase in acquisition spend."
        )

    asyncio.run(scenario())


def test_generation_fails_closed_before_persistence_for_invalid_inputs() -> None:
    request_id, blueprint, sources = load_generation_request()

    async def scenario() -> None:
        writer = RecordingArtifactWriter()
        manifests = MemoryManifestRepository()
        generator = DecisionPacketGenerator(writer, manifests)

        with pytest.raises(PacketGenerationError, match="request ID"):
            await generator.generate("", blueprint, sources, NOW)
        with pytest.raises(PacketGenerationError, match="At least one"):
            await generator.generate(request_id, blueprint, (), NOW)
        with pytest.raises(PacketGenerationError, match="unique"):
            await generator.generate(request_id, blueprint, (*sources, sources[0]), NOW)

        unknown_source_claim = blueprint.claims[0].model_copy(
            update={"source_ids": ("missing-source",)}
        )
        invalid_blueprint = blueprint.model_copy(
            update={"claims": (unknown_source_claim, *blueprint.claims[1:])}
        )
        with pytest.raises(PacketGenerationError, match="unknown source"):
            await generator.generate(request_id, invalid_blueprint, sources, NOW)

        unknown_artifact_claim = blueprint.claims[0].model_copy(
            update={
                "artifact_targets": (
                    blueprint.claims[0]
                    .artifact_targets[0]
                    .model_copy(update={"artifact_id": "missing-artifact"}),
                )
            }
        )
        invalid_blueprint = blueprint.model_copy(
            update={"claims": (unknown_artifact_claim, *blueprint.claims[1:])}
        )
        with pytest.raises(PacketGenerationError, match="unknown artifact"):
            await generator.generate(request_id, invalid_blueprint, sources, NOW)

        unused_artifact = ArtifactBlueprint(
            artifact_id="unused",
            kind=ArtifactKind.GOOGLE_DOC,
            title="Unused",
            mutability=ArtifactMutability.EDITABLE,
        )
        invalid_blueprint = blueprint.model_copy(
            update={"artifacts": (*blueprint.artifacts, unused_artifact)}
        )
        with pytest.raises(PacketGenerationError, match="Every packet artifact"):
            await generator.generate(request_id, invalid_blueprint, sources, NOW)

        unknown_transform = blueprint.claims[0].model_copy(
            update={"transformation": "not_registered"}
        )
        invalid_blueprint = blueprint.model_copy(
            update={"claims": (unknown_transform, *blueprint.claims[1:])}
        )
        with pytest.raises(PacketGenerationError, match="Unknown transformation"):
            await generator.generate(request_id, invalid_blueprint, sources, NOW)

        assert writer.calls == []
        assert manifests.persist_calls == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("writer", "message"),
    [
        (RecordingArtifactWriter(omit_anchor=True), "every provenance anchor"),
        (RecordingArtifactWriter(wrong_artifact=True), "unexpected artifact set"),
    ],
)
def test_generation_rejects_invalid_artifact_writer_results(
    writer: RecordingArtifactWriter,
    message: str,
) -> None:
    request_id, blueprint, sources = load_generation_request()
    manifests = MemoryManifestRepository()

    async def scenario() -> None:
        with pytest.raises(PacketGenerationError, match=message):
            await DecisionPacketGenerator(writer, manifests).generate(
                request_id, blueprint, sources, NOW
            )
        assert manifests.persist_calls == 0

    asyncio.run(scenario())
