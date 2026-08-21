import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from lineage_support import NOW, MemoryImpactRepository, meaningful_snapshot
from veritas_runtime.lineage.routes import create_impact_router
from veritas_runtime.lineage.service import (
    ImpactAnalysisError,
    ImpactAnalysisService,
    ImpactIdempotencyConflict,
)

PACKET_ID = "packet-q3-executive-review"


def test_impact_service_is_idempotent_and_rejects_conflicting_reuse() -> None:
    second = meaningful_snapshot("src-nps", snapshot_id="snapshot-nps-changed")
    repository = MemoryImpactRepository(snapshots=(meaningful_snapshot(), second))
    service = ImpactAnalysisService(repository)

    async def scenario() -> None:
        first = await service.analyze(
            "subject-1",
            PACKET_ID,
            "impact-request-1",
            ("snapshot-src-churn-changed",),
            NOW,
        )
        replay = await service.analyze(
            "subject-1",
            PACKET_ID,
            "impact-request-1",
            ("snapshot-src-churn-changed",),
            NOW,
        )
        assert first.reused is False
        assert replay.reused is True
        assert replay.report == first.report
        with pytest.raises(ImpactIdempotencyConflict, match="different lineage inputs"):
            await service.analyze(
                "subject-1",
                PACKET_ID,
                "impact-request-1",
                ("snapshot-nps-changed",),
                NOW,
            )
        with pytest.raises(ImpactAnalysisError, match="required"):
            await service.analyze("", PACKET_ID, "request", (), NOW)

    asyncio.run(scenario())


def _app(
    service: ImpactAnalysisService | None,
    *,
    subject: str | None = "subject-1",
) -> FastAPI:
    async def resolver(_request: Request) -> str:
        assert subject is not None
        return subject

    app = FastAPI()
    app.include_router(create_impact_router(service, resolver if subject is not None else None))
    return app


def test_impact_api_fails_closed_then_returns_golden_registered_graph() -> None:
    disabled = TestClient(_app(None, subject=None))
    assert disabled.get("/api/v1/lineage/capabilities").json() == {"registeredBlastRadius": False}
    assert (
        disabled.post(
            f"/api/v1/packets/{PACKET_ID}/impact",
            json={
                "requestId": "request-1",
                "snapshotIds": ["snapshot-src-churn-changed"],
            },
        ).status_code
        == 503
    )

    client = TestClient(_app(ImpactAnalysisService(MemoryImpactRepository())))
    response = client.post(
        f"/api/v1/packets/{PACKET_ID}/impact",
        json={
            "requestId": "request-1",
            "snapshotIds": ["snapshot-src-churn-changed"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["report"]["affectedClaims"]) == 4
    assert len(payload["report"]["affectedArtifacts"]) == 5
    assert payload["report"]["candidateClaimIds"] == []
    assert len(payload["checksum"]) == 64


def test_impact_api_maps_access_missing_and_lineage_failures() -> None:
    denied = TestClient(
        _app(ImpactAnalysisService(MemoryImpactRepository()), subject="wrong-subject")
    )
    payload = {
        "requestId": "request-1",
        "snapshotIds": ["snapshot-src-churn-changed"],
    }
    assert denied.post(f"/api/v1/packets/{PACKET_ID}/impact", json=payload).status_code == 403

    client = TestClient(_app(ImpactAnalysisService(MemoryImpactRepository())))
    assert (
        client.post(
            f"/api/v1/packets/{PACKET_ID}/impact",
            json={"requestId": "request-2", "snapshotIds": ["missing"]},
        ).status_code
        == 404
    )

    cosmetic = meaningful_snapshot(delta_kind="cosmetic")  # type: ignore[arg-type]
    cosmetic_repository = MemoryImpactRepository(snapshots=(cosmetic,))
    cosmetic_client = TestClient(_app(ImpactAnalysisService(cosmetic_repository)))
    assert (
        cosmetic_client.post(f"/api/v1/packets/{PACKET_ID}/impact", json=payload).status_code == 400
    )
