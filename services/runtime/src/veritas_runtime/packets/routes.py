from collections.abc import Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from veritas_runtime.packets.generator import (
    DecisionPacketGenerator,
    IdempotencyConflict,
    PacketGenerationError,
)
from veritas_runtime.packets.models import (
    CamelModel,
    DecisionPacketBlueprint,
    PacketGenerationResult,
    SourceSnapshot,
)
from veritas_runtime.packets.service import WorkspacePacketGenerationService

SubjectResolver = Callable[[Request], Awaitable[str]]


class GeneratePacketRequest(CamelModel):
    request_id: str
    blueprint: DecisionPacketBlueprint
    sources: tuple[SourceSnapshot, ...]


def create_packet_router(
    generator: DecisionPacketGenerator | None,
    subject_service: WorkspacePacketGenerationService | None = None,
    subject_resolver: SubjectResolver | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/packets/capabilities", tags=["packets"])
    async def packet_capabilities() -> dict[str, bool]:
        return {
            "liveWorkspaceGeneration": generator is not None
            or (subject_service is not None and subject_resolver is not None)
        }

    @router.post(
        "/api/v1/packets",
        response_model=PacketGenerationResult,
        tags=["packets"],
    )
    async def generate_packet(
        payload: GeneratePacketRequest, request: Request
    ) -> PacketGenerationResult:
        if generator is None and (subject_service is None or subject_resolver is None):
            raise HTTPException(
                status_code=503,
                detail="Google Workspace packet generation is not configured",
            )
        try:
            if subject_service is not None and subject_resolver is not None:
                return await subject_service.generate_for_subject(
                    await subject_resolver(request),
                    payload.request_id,
                    payload.blueprint,
                    payload.sources,
                )
            assert generator is not None
            return await generator.generate(
                payload.request_id,
                payload.blueprint,
                payload.sources,
            )
        except IdempotencyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except PacketGenerationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="Google Workspace access denied") from error

    return router
