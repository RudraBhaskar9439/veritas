from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from veritas_runtime.lineage.engine import LineageIntegrityError
from veritas_runtime.lineage.models import ImpactAnalysisResult, ImpactRequest
from veritas_runtime.lineage.service import (
    ImpactAnalysisError,
    ImpactAnalysisService,
    ImpactIdempotencyConflict,
)

SubjectResolver = Callable[[Request], Awaitable[str]]


def create_impact_router(
    service: ImpactAnalysisService | None,
    subject_resolver: SubjectResolver | None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/lineage/capabilities", tags=["lineage"])
    async def capabilities() -> dict[str, bool]:
        return {"registeredBlastRadius": service is not None and subject_resolver is not None}

    @router.post(
        "/api/v1/packets/{packet_id}/impact",
        response_model=ImpactAnalysisResult,
        tags=["lineage"],
    )
    async def analyze_impact(
        packet_id: str,
        payload: ImpactRequest,
        request: Request,
    ) -> ImpactAnalysisResult:
        if service is None or subject_resolver is None:
            raise HTTPException(
                status_code=503,
                detail="Registered lineage analysis is not configured",
            )
        subject = await subject_resolver(request)
        try:
            return await service.analyze(
                subject,
                packet_id,
                payload.request_id,
                payload.snapshot_ids,
            )
        except ImpactIdempotencyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (ImpactAnalysisError, LineageIntegrityError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Packet access denied") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return router
