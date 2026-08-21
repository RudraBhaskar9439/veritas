from fastapi import APIRouter, HTTPException

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


class GeneratePacketRequest(CamelModel):
    request_id: str
    blueprint: DecisionPacketBlueprint
    sources: tuple[SourceSnapshot, ...]


def create_packet_router(generator: DecisionPacketGenerator | None) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/packets/capabilities", tags=["packets"])
    async def packet_capabilities() -> dict[str, bool]:
        return {"liveWorkspaceGeneration": generator is not None}

    @router.post(
        "/api/v1/packets",
        response_model=PacketGenerationResult,
        tags=["packets"],
    )
    async def generate_packet(request: GeneratePacketRequest) -> PacketGenerationResult:
        if generator is None:
            raise HTTPException(
                status_code=503,
                detail="Google Workspace packet generation is not configured",
            )
        try:
            return await generator.generate(
                request.request_id,
                request.blueprint,
                request.sources,
            )
        except IdempotencyConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except PacketGenerationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return router
