from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from veritas_runtime.verification.models import VerificationResult, VerifyRepairRequest
from veritas_runtime.verification.service import (
    VerificationIdempotencyConflict,
    VerificationIntegrityError,
    VerificationService,
)

SubjectResolver = Callable[[Request], Awaitable[str]]


def create_verification_router(
    service: VerificationService | None,
    subject_resolver: SubjectResolver | None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/verification/capabilities", tags=["verification"])
    async def capabilities() -> dict[str, bool]:
        return {"independentVerification": service is not None and subject_resolver is not None}

    @router.post(
        "/api/v1/repair-runs/{run_id}/verify",
        response_model=VerificationResult,
        tags=["verification"],
    )
    async def verify_run(
        run_id: str,
        payload: VerifyRepairRequest,
        request: Request,
    ) -> VerificationResult:
        if service is None or subject_resolver is None:
            raise HTTPException(
                status_code=503, detail="Independent verification is not configured"
            )
        subject = await subject_resolver(request)
        try:
            return await service.verify(subject, run_id, payload.request_id)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Verification denied") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except VerificationIdempotencyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except VerificationIntegrityError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return router
