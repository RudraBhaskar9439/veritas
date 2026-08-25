import asyncio
from collections.abc import Awaitable, Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from packet_support import load_generation_request
from veritas_runtime.changes.bootstrap import (
    EvidenceBootstrapError,
    GoogleWorkspaceEvidenceBootstrapper,
    WorkspaceEvidenceBootstrapService,
)
from veritas_runtime.changes.routes_bootstrap import create_evidence_bootstrap_router
from veritas_runtime.execution.service import WorkspaceSession
from veritas_runtime.packets.models import SourceSnapshot
from veritas_runtime.workspace.contracts import WorkspaceAuthorization


class StaticSessions:
    async def get(self, subject: str) -> WorkspaceSession:
        assert subject == "subject-1"
        return WorkspaceSession(
            access_token="access-token",
            authorization=WorkspaceAuthorization(frozenset()),
            email="owner@example.test",
        )


def _sources() -> tuple[SourceSnapshot, ...]:
    return load_generation_request()[2]


def test_bootstrap_materializes_sheet_and_doc_with_real_versions() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer access-token"
        path = request.url.path
        if request.method == "GET" and path == "/drive/v3/files":
            return httpx.Response(200, json={"files": []})
        if request.method == "POST" and path == "/v4/spreadsheets":
            return httpx.Response(200, json={"spreadsheetId": "real-sheet"})
        if request.method == "POST" and path.endswith("/values:batchUpdate"):
            return httpx.Response(200, json={})
        if request.method == "POST" and path == "/v1/documents":
            return httpx.Response(200, json={"documentId": "real-doc"})
        if request.method == "POST" and path.endswith(":batchUpdate"):
            return httpx.Response(200, json={})
        if request.method == "PATCH":
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[-1]})
        if request.method == "GET" and path.endswith("/real-sheet"):
            return httpx.Response(200, json={"version": 7})
        if request.method == "GET" and path.endswith("/real-doc"):
            return httpx.Response(200, json={"version": "9"})
        raise AssertionError(f"Unexpected Workspace request: {request.method} {request.url}")

    async def scenario() -> tuple[SourceSnapshot, ...]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = WorkspaceEvidenceBootstrapService(StaticSessions(), client)
            return await service.bootstrap_for_subject("subject-1", "request-1", _sources())

    resolved = asyncio.run(scenario())
    assert {source.resource_id for source in resolved} == {"real-sheet", "real-doc"}
    assert {source.version for source in resolved} == {"7", "9"}
    sheet_write = next(
        request for request in requests if request.url.path.endswith("values:batchUpdate")
    )
    assert b'"range":"Metrics!B17"' in sheet_write.content
    doc_write = next(
        request
        for request in requests
        if request.url.host == "docs.googleapis.com"
        and request.url.path.endswith(":batchUpdate")
    )
    assert b'"name":"launch-date"' in doc_write.content


def test_bootstrap_reuses_uniquely_marked_workspace_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drive/v3/files":
            query = request.url.params["q"]
            resource_id = "existing-doc" if "document" in query else "existing-sheet"
            return httpx.Response(200, json={"files": [{"id": resource_id}]})
        if request.url.path.endswith("existing-sheet"):
            return httpx.Response(200, json={"version": "11"})
        if request.url.path.endswith("existing-doc"):
            return httpx.Response(200, json={"version": 12})
        raise AssertionError(f"A reused source must not be recreated: {request.url}")

    async def scenario() -> tuple[SourceSnapshot, ...]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await GoogleWorkspaceEvidenceBootstrapper(
                "access-token", client
            ).materialize("request-1", _sources())

    resolved = asyncio.run(scenario())
    assert {source.resource_id for source in resolved} == {"existing-sheet", "existing-doc"}
    assert {source.version for source in resolved} == {"11", "12"}


def test_bootstrap_rejects_invalid_evidence_and_workspace_responses() -> None:
    sheet = _sources()[0]
    document = _sources()[-1]

    async def invalid_requests() -> None:
        async with httpx.AsyncClient() as client:
            bootstrapper = GoogleWorkspaceEvidenceBootstrapper("access-token", client)
            for request_id, sources in (("", (sheet,)), ("request", ())):
                try:
                    await bootstrapper.materialize(request_id, sources)
                except EvidenceBootstrapError as error:
                    assert "required" in str(error)
                else:
                    raise AssertionError("Invalid evidence input was accepted")
            mixed = (sheet, document.model_copy(update={"resource_id": sheet.resource_id}))
            try:
                await bootstrapper.materialize("request", mixed)
            except EvidenceBootstrapError as error:
                assert "mix" in str(error)
            else:
                raise AssertionError("Mixed Workspace kinds were accepted")

        def ambiguous(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"files": [{"id": "a"}, {"id": "b"}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(ambiguous)) as client:
            try:
                await GoogleWorkspaceEvidenceBootstrapper(
                    "access-token", client
                ).materialize("request", (sheet,))
            except EvidenceBootstrapError as error:
                assert "ambiguous" in str(error)
            else:
                raise AssertionError("Ambiguous evidence identity was accepted")

        def rejected(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "denied"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(rejected)) as client:
            try:
                await GoogleWorkspaceEvidenceBootstrapper(
                    "access-token", client
                ).materialize("request", (sheet,))
            except EvidenceBootstrapError as error:
                assert "status 403" in str(error)
            else:
                raise AssertionError("Workspace rejection was ignored")

    asyncio.run(invalid_requests())


class RecordingBootstrapService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def bootstrap_for_subject(
        self,
        subject: str,
        request_id: str,
        sources: tuple[SourceSnapshot, ...],
    ) -> tuple[SourceSnapshot, ...]:
        if self.error is not None:
            raise self.error
        assert subject == "subject-1"
        assert request_id == "request-1"
        return sources


def _route_app(
    service: RecordingBootstrapService | None,
    resolver: Callable[[Request], Awaitable[str]] | None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(create_evidence_bootstrap_router(service, resolver))  # type: ignore[arg-type]
    return app


def _route_payload() -> dict[str, object]:
    return {
        "requestId": "request-1",
        "sources": [source.model_dump(mode="json", by_alias=True) for source in _sources()],
    }


def test_evidence_bootstrap_route_authenticates_and_fails_closed() -> None:
    async def subject(_request: Request) -> str:
        return "subject-1"

    assert TestClient(_route_app(None, None)).post(
        "/api/v1/evidence/bootstrap", json=_route_payload()
    ).status_code == 503
    response = TestClient(_route_app(RecordingBootstrapService(), subject)).post(
        "/api/v1/evidence/bootstrap", json=_route_payload()
    )
    assert response.status_code == 200
    assert len(response.json()["sources"]) == 6
    denied = TestClient(
        _route_app(RecordingBootstrapService(PermissionError("denied")), subject)
    ).post("/api/v1/evidence/bootstrap", json=_route_payload())
    assert denied.status_code == 403
    invalid = TestClient(
        _route_app(RecordingBootstrapService(EvidenceBootstrapError("invalid")), subject)
    ).post("/api/v1/evidence/bootstrap", json=_route_payload())
    assert invalid.status_code == 400
