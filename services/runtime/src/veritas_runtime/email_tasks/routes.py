from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query

from veritas_runtime.auth.sessions import SessionPrincipal
from veritas_runtime.email_tasks.models import (
    EmailTaskEvent,
    EmailTaskRegistrationResult,
    EmailTaskSetup,
    EmailTaskWorkflow,
    RegisterEmailTaskWorkflowRequest,
)
from veritas_runtime.email_tasks.service import (
    EmailTaskRegistrationCoordinator,
    EmailTaskWorkflowError,
)


class PrincipalResolver(Protocol):
    async def __call__(self) -> SessionPrincipal: ...


def create_email_task_router(
    coordinator: EmailTaskRegistrationCoordinator | None,
    principal_resolver: object | None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/email-task-workflows/capabilities", tags=["email-tasks"])
    async def capabilities() -> dict[str, bool]:
        return {"acceptingEmailTaskWorkflows": coordinator is not None}

    if coordinator is None or principal_resolver is None:

        @router.get("/api/v1/email-task-workflows", tags=["email-tasks"])
        async def unavailable_list() -> list[object]:
            raise HTTPException(status_code=503, detail="Email-task workflows are not configured")

        @router.post("/api/v1/email-task-workflows", tags=["email-tasks"])
        async def unavailable_create() -> None:
            raise HTTPException(status_code=503, detail="Email-task workflows are not configured")

        @router.get("/api/v1/email-task-workflows/setup", tags=["email-tasks"])
        async def unavailable_setup() -> None:
            raise HTTPException(status_code=503, detail="Email-task workflows are not configured")

        @router.get("/api/v1/email-task-events", tags=["email-tasks"])
        async def unavailable_events() -> None:
            raise HTTPException(status_code=503, detail="Email-task workflows are not configured")

        @router.delete("/api/v1/email-task-workflows/{workflow_id}", tags=["email-tasks"])
        async def unavailable_pause(workflow_id: str) -> None:
            raise HTTPException(status_code=503, detail="Email-task workflows are not configured")

        return router

    resolver = principal_resolver

    @router.get("/api/v1/email-task-workflows", tags=["email-tasks"])
    async def list_workflows(
        principal: Annotated[SessionPrincipal, Depends(resolver)],
    ) -> tuple[EmailTaskWorkflow, ...]:
        return await coordinator.list(principal.subject)

    @router.get("/api/v1/email-task-workflows/setup", tags=["email-tasks"])
    async def workflow_setup(
        principal: Annotated[SessionPrincipal, Depends(resolver)],
        packet_id: Annotated[str, Query(alias="packetId", min_length=1, max_length=255)],
    ) -> EmailTaskSetup:
        try:
            return await coordinator.setup(principal.subject, principal.email, packet_id)
        except EmailTaskWorkflowError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/api/v1/email-task-events", tags=["email-tasks"])
    async def list_events(
        principal: Annotated[SessionPrincipal, Depends(resolver)],
        packet_id: Annotated[str, Query(alias="packetId", min_length=1, max_length=255)],
    ) -> tuple[EmailTaskEvent, ...]:
        try:
            return await coordinator.list_events(principal.subject, packet_id)
        except EmailTaskWorkflowError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.delete("/api/v1/email-task-workflows/{workflow_id}", tags=["email-tasks"])
    async def pause_workflow(
        workflow_id: str,
        principal: Annotated[SessionPrincipal, Depends(resolver)],
    ) -> EmailTaskWorkflow:
        try:
            return await coordinator.pause(principal.subject, workflow_id)
        except EmailTaskWorkflowError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.post("/api/v1/email-task-workflows", tags=["email-tasks"])
    async def register_workflow(
        request: RegisterEmailTaskWorkflowRequest,
        principal: Annotated[SessionPrincipal, Depends(resolver)],
    ) -> EmailTaskRegistrationResult:
        try:
            return await coordinator.register(
                principal.subject,
                principal.email,
                request,
            )
        except EmailTaskWorkflowError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    return router
