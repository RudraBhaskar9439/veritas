from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from veritas_runtime.changes.bootstrap import (
    EvidenceBootstrapError,
    WorkspaceEvidenceBootstrapService,
)
from veritas_runtime.packets.models import CamelModel, SourceSnapshot

SubjectResolver = Callable[[Request], Awaitable[str]]


class BootstrapEvidenceRequest(CamelModel):
    request_id: str
    sources: tuple[SourceSnapshot, ...]


class BootstrapEvidenceResult(CamelModel):
    sources: tuple[SourceSnapshot, ...]


def create_evidence_bootstrap_router(
    service: WorkspaceEvidenceBootstrapService | None,
    subject_resolver: SubjectResolver | None,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/v1/evidence/bootstrap",
        response_model=BootstrapEvidenceResult,
        tags=["evidence"],
    )
    async def bootstrap_evidence(
        payload: BootstrapEvidenceRequest,
        request: Request,
    ) -> BootstrapEvidenceResult:
        if service is None or subject_resolver is None:
            raise HTTPException(status_code=503, detail="Evidence bootstrap is not configured")
        try:
            sources = await service.bootstrap_for_subject(
                await subject_resolver(request),
                payload.request_id,
                payload.sources,
            )
        except EvidenceBootstrapError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Google Workspace access denied") from error
        return BootstrapEvidenceResult(sources=sources)

    return router
