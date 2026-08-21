from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from veritas_runtime.execution.models import ExecuteRepairRequest, RepairRun
from veritas_runtime.execution.service import RepairExecutionService

SubjectResolver = Callable[[Request], Awaitable[str]]


def create_execution_router(
    service: RepairExecutionService | None,
    subject_resolver: SubjectResolver | None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/execution/capabilities", tags=["execution"])
    async def capabilities() -> dict[str, bool]:
        return {"workspaceExecution": service is not None and subject_resolver is not None}

    @router.post(
        "/api/v1/repair-plans/{plan_id}/execute",
        response_model=RepairRun,
        tags=["execution"],
    )
    async def execute_plan(
        plan_id: str,
        payload: ExecuteRepairRequest,
        request: Request,
    ) -> RepairRun:
        if service is None or subject_resolver is None:
            raise HTTPException(status_code=503, detail="Workspace execution is not configured")
        subject = await subject_resolver(request)
        try:
            return await service.execute(subject, plan_id, payload.request_id)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Repair execution denied") from error
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return router
