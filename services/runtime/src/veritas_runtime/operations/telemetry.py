import structlog


class StructuredLogOperationTelemetry:
    """Emit bounded, payload-free operational events for Cloud Logging metrics."""

    def __init__(self) -> None:
        self._logger = structlog.get_logger()

    async def emit(self, event: str, **fields: str | int | bool | None) -> None:
        await self._logger.ainfo(event, **fields)
