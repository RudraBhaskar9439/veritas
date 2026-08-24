from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from veritas_runtime.command_center.models import (
    CommandCenterApprovalRequest,
    CommandCenterApprovalResult,
    CommandCenterIncident,
)
from veritas_runtime.command_center.service import CommandCenterService
from veritas_runtime.orchestration import HumanApprovalContinuation
from veritas_runtime.repairs.models import ApprovalActor
from veritas_runtime.repairs.service import ApprovalConflict, RepairPlanningError
from veritas_runtime.verification.service import (
    VerificationIdempotencyConflict,
    VerificationIntegrityError,
)

SubjectResolver = Callable[[Request], Awaitable[str]]
ActorResolver = Callable[[Request], Awaitable[ApprovalActor]]


def create_command_center_router(
    service: CommandCenterService | None,
    subject_resolver: SubjectResolver | None,
    continuation: HumanApprovalContinuation | None = None,
    actor_resolver: ActorResolver | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/command-center/capabilities", tags=["command-center"])
    async def capabilities() -> dict[str, bool]:
        configured = service is not None and subject_resolver is not None
        return {
            "liveReadModel": configured,
            "approvalContinuation": configured
            and continuation is not None
            and actor_resolver is not None,
        }

    @router.get(
        "/api/v1/command-center/incidents/latest",
        response_model=CommandCenterIncident | None,
        tags=["command-center"],
    )
    async def latest(request: Request) -> CommandCenterIncident | None:
        if service is None or subject_resolver is None:
            raise HTTPException(status_code=503, detail="Command Center is not configured")
        return await service.latest(await subject_resolver(request))

    @router.get(
        "/api/v1/command-center/incidents/{plan_id}",
        response_model=CommandCenterIncident,
        tags=["command-center"],
    )
    async def incident(plan_id: str, request: Request) -> CommandCenterIncident:
        if service is None or subject_resolver is None:
            raise HTTPException(status_code=503, detail="Command Center is not configured")
        try:
            return await service.get(await subject_resolver(request), plan_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.post(
        "/api/v1/command-center/incidents/{plan_id}/runs/{run_id}/approvals/{approval_id}",
        response_model=CommandCenterApprovalResult,
        tags=["command-center"],
    )
    async def decide_and_continue(
        plan_id: str,
        run_id: str,
        approval_id: str,
        payload: CommandCenterApprovalRequest,
        request: Request,
    ) -> CommandCenterApprovalResult:
        if continuation is None or subject_resolver is None or actor_resolver is None:
            raise HTTPException(status_code=503, detail="Approval continuation is not configured")
        subject = await subject_resolver(request)
        actor = await actor_resolver(request)
        try:
            return await continuation.decide(
                subject,
                actor,
                plan_id,
                run_id,
                approval_id,
                payload,
            )
        except (ApprovalConflict, VerificationIdempotencyConflict) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (RepairPlanningError, VerificationIntegrityError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Approval continuation denied") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return router
