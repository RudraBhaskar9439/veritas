import asyncio

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine

from packet_support import NOW, RecordingArtifactWriter, load_generation_request
from veritas_runtime.auth.database import metadata
from veritas_runtime.packets.database import SqlManifestRepository, claim_manifests
from veritas_runtime.packets.generator import DecisionPacketGenerator, IdempotencyConflict


def test_sql_manifest_repository_versions_replays_and_checks_integrity() -> None:
    request_id, blueprint, sources = load_generation_request()

    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        repository = SqlManifestRepository(engine)
        generator = DecisionPacketGenerator(RecordingArtifactWriter(), repository)

        first = await generator.generate(request_id, blueprint, sources, NOW)
        replay = await generator.generate(request_id, blueprint, sources, NOW)
        assert first.manifest.version == 1
        assert replay.reused is True
        assert replay.checksum == first.checksum

        changed_sources = tuple(
            source.model_copy(update={"value": 0.09}) if source.source_id == "src-churn" else source
            for source in sources
        )
        with pytest.raises(IdempotencyConflict, match="different inputs"):
            await generator.generate(request_id, blueprint, changed_sources, NOW)
        second = await generator.generate("changed-request", blueprint, changed_sources, NOW)
        assert second.manifest.version == 2

        async with engine.begin() as connection:
            await connection.execute(
                update(claim_manifests)
                .where(claim_manifests.c.idempotency_key == f"{blueprint.packet_id}:{request_id}")
                .values(checksum="0" * 64)
            )
        with pytest.raises(ValueError, match="checksum mismatch"):
            await repository.get_by_idempotency_key(f"{blueprint.packet_id}:{request_id}")
        await engine.dispose()

    asyncio.run(scenario())
