import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from execution_support import StaticWorkspaceSessions
from verification_support import (
    NOW,
    MemoryIndependentVerifier,
    MemoryVerificationRepository,
    canonical_verification_context,
)
from veritas_runtime.verification.routes import create_verification_router
from veritas_runtime.verification.service import (
    ProtectedRegionBaselineService,
    VerificationService,
)


def test_pre_mutation_baselines_are_complete_and_immutable_on_replay() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        repository = MemoryVerificationRepository(context)
        repository.baselines = ()
        gateway = MemoryIndependentVerifier(context)
        service = ProtectedRegionBaselineService(repository, gateway)
        await service.capture("subject-1", context.run, context.plan, "access-token", NOW)
        first = repository.baselines
        assert len(first) == 5
        await service.capture("subject-1", context.run, context.plan, "access-token", NOW)
        assert repository.baselines == first

    asyncio.run(scenario())


def test_pre_mutation_baseline_accepts_an_authorized_statement_already_repaired() -> None:
    async def scenario() -> None:
        context = await canonical_verification_context()
        repository = MemoryVerificationRepository(context)
        repository.baselines = ()
        gateway = MemoryIndependentVerifier(context)
        task_step = next(
            step for step in context.plan.steps if step.artifact_kind.value == "google_task"
        )
        gateway.registered[(task_step.artifact_id, task_step.anchor)] = (
            task_step.proposed_statement
        )
        service = ProtectedRegionBaselineService(repository, gateway)

        await service.capture("subject-1", context.run, context.plan, "access-token", NOW)

        assert len(repository.baselines) == 5

    asyncio.run(scenario())


def test_verification_route_fails_closed_when_dependencies_are_absent() -> None:
    app = FastAPI()
    app.include_router(create_verification_router(None, None))
    client = TestClient(app)
    assert client.get("/api/v1/verification/capabilities").json() == {
        "independentVerification": False
    }
    response = client.post(
        "/api/v1/repair-runs/run-1/verify",
        json={"requestId": "verify-1"},
    )
    assert response.status_code == 503


def test_verification_route_returns_a_verified_result_with_trusted_identity() -> None:
    async def subject_resolver(_) -> str:  # type: ignore[no-untyped-def]
        return "subject-1"

    async def build():  # type: ignore[no-untyped-def]
        context = await canonical_verification_context()
        service = VerificationService(
            MemoryVerificationRepository(context),
            StaticWorkspaceSessions(),
            MemoryIndependentVerifier(context),
        )
        return context, service

    context, service = asyncio.run(build())
    app = FastAPI()
    app.include_router(create_verification_router(service, subject_resolver))
    response = TestClient(app).post(
        f"/api/v1/repair-runs/{context.run.run_id}/verify",
        json={"requestId": "verify-route"},
    )
    assert response.status_code == 200
    assert response.json()["report"]["status"] == "verified"
    assert response.json()["certificate"]["statement"].startswith("All monitored claims")
