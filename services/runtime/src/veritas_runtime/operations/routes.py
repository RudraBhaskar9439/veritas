from collections.abc import Awaitable, Callable
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request

from veritas_runtime.operations.models import (
    DeadLetterSummary,
    ReplayOperationRequest,
    ReplayOperationResult,
    WorkerTickRequest,
)
from veritas_runtime.operations.service import ReliableOperationService

SubjectResolver = Callable[[Request], Awaitable[str]]
ActorResolver = Callable[[Request], Awaitable[str]]


class WorkerOperationService(Protocol):
    async def tick(self, worker_id: str) -> object: ...


def create_operations_router(
    service: ReliableOperationService | None,
    subject_resolver: SubjectResolver | None,
    actor_resolver: ActorResolver | None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/operations/capabilities", tags=["operations"])
    async def capabilities() -> dict[str, bool]:
        configured = (
            service is not None and subject_resolver is not None and actor_resolver is not None
        )
        return {
            "deadLetterInspection": configured,
            "auditedReplay": configured,
        }

    @router.get(
        "/api/v1/operations/dead-letters",
        response_model=tuple[DeadLetterSummary, ...],
        tags=["operations"],
    )
    async def dead_letters(request: Request) -> tuple[DeadLetterSummary, ...]:
        if service is None or subject_resolver is None:
            raise HTTPException(status_code=503, detail="Operations recovery is not configured")
        return await service.list_dead_letters(await subject_resolver(request))

    @router.post(
        "/api/v1/operations/dead-letters/{operation_id}/replay",
        response_model=ReplayOperationResult,
        tags=["operations"],
    )
    async def replay(
        operation_id: str,
        payload: ReplayOperationRequest,
        request: Request,
    ) -> ReplayOperationResult:
        if service is None or subject_resolver is None or actor_resolver is None:
            raise HTTPException(status_code=503, detail="Operations recovery is not configured")
        try:
            operation, reused = await service.replay(
                await subject_resolver(request),
                operation_id,
                payload.request_id,
                await actor_resolver(request),
                payload.reason,
            )
            return ReplayOperationResult(operation=operation, reused=reused)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return router


def create_worker_operations_router(service: WorkerOperationService | None) -> APIRouter:
    router = APIRouter()

    @router.get("/internal/v1/operations/capabilities", tags=["operations"])
    async def capabilities() -> dict[str, bool]:
        return {
            "durableLeases": service is not None,
            "boundedRetries": service is not None,
            "deadLetters": service is not None,
        }

    @router.post("/internal/v1/operations/tick", tags=["operations"])
    async def tick(payload: WorkerTickRequest) -> object:
        if service is None:
            raise HTTPException(status_code=503, detail="Reliable worker is not configured")
        return await service.tick(payload.worker_id)

    return router
