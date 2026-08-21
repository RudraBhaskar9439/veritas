from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from veritas_runtime.repairs.models import (
    ApprovalActor,
    ApprovalDecisionRequest,
    ApprovalDecisionResult,
    RepairPlanRequest,
    RepairPlanResult,
)
from veritas_runtime.repairs.planner import RepairPlanningIntegrityError
from veritas_runtime.repairs.service import (
    ApprovalConflict,
    RepairPlanIdempotencyConflict,
    RepairPlanningError,
    RepairPlanningService,
)

SubjectResolver = Callable[[Request], Awaitable[str]]
ActorResolver = Callable[[Request], Awaitable[ApprovalActor]]


def create_repair_router(
    service: RepairPlanningService | None,
    subject_resolver: SubjectResolver | None,
    actor_resolver: ActorResolver | None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/repairs/capabilities", tags=["repairs"])
    async def capabilities() -> dict[str, bool]:
        configured = (
            service is not None and subject_resolver is not None and actor_resolver is not None
        )
        return {
            "typedPlanning": configured,
            "humanApprovals": configured,
            "execution": False,
        }

    @router.post(
        "/api/v1/packets/{packet_id}/repair-plans",
        response_model=RepairPlanResult,
        tags=["repairs"],
    )
    async def create_plan(
        packet_id: str,
        payload: RepairPlanRequest,
        request: Request,
    ) -> RepairPlanResult:
        if service is None or subject_resolver is None:
            raise HTTPException(status_code=503, detail="Repair planning is not configured")
        subject = await subject_resolver(request)
        try:
            return await service.create_plan(
                subject,
                packet_id,
                payload.request_id,
                payload.impact_report_id,
            )
        except RepairPlanIdempotencyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (RepairPlanningError, RepairPlanningIntegrityError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Packet access denied") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.post(
        "/api/v1/repair-plans/{plan_id}/approvals/{approval_id}",
        response_model=ApprovalDecisionResult,
        tags=["repairs"],
    )
    async def decide_approval(
        plan_id: str,
        approval_id: str,
        payload: ApprovalDecisionRequest,
        request: Request,
    ) -> ApprovalDecisionResult:
        if service is None or subject_resolver is None or actor_resolver is None:
            raise HTTPException(status_code=503, detail="Human approvals are not configured")
        subject = await subject_resolver(request)
        actor = await actor_resolver(request)
        try:
            return await service.decide_approval(
                subject,
                actor,
                plan_id,
                approval_id,
                payload.request_id,
                payload.decision,
                payload.reason,
            )
        except ApprovalConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RepairPlanningError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Human approval denied") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return router
