import asyncio
import json

import httpx
import pytest

from veritas_runtime.packets.google import (
    GoogleWorkspacePacketWriter,
    WorkspacePacketWriteError,
)
from veritas_runtime.packets.models import (
    AnchoredClaimBlock,
    ArtifactKind,
    ArtifactMutability,
    PacketArtifactDraft,
)


def _draft(kind: ArtifactKind, artifact_id: str = "artifact-1") -> PacketArtifactDraft:
    return PacketArtifactDraft(
        artifact_id=artifact_id,
        kind=kind,
        title=f"Test {kind.value}",
        mutability=(
            ArtifactMutability.IMMUTABLE
            if kind == ArtifactKind.GMAIL
            else ArtifactMutability.EDITABLE
        ),
        claim_blocks=(
            AnchoredClaimBlock(
                claim_id="claim-1",
                slot="claim-slot-1",
                statement="Customer churn is 9%.",
            ),
            AnchoredClaimBlock(
                claim_id="claim-2",
                slot="claim-slot-2",
                statement="Retention needs attention.",
            ),
        ),
    )


def test_google_packet_writer_creates_native_anchored_artifacts() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/drive/v3/files" and request.method == "GET":
            return httpx.Response(200, json={"files": []})
        if path == "/v1/documents" and request.method == "POST":
            return httpx.Response(200, json={"documentId": "doc-1"})
        if path == "/v1/documents/doc-1:batchUpdate":
            body = json.loads(request.content)
            assert len(body["requests"]) == 3
            assert body["requests"][1]["createNamedRange"]["name"] == "claim-slot-1"
            return httpx.Response(200, json={})
        if path == "/v1/documents/doc-1" and request.method == "GET":
            return httpx.Response(200, json={"documentId": "doc-1", "revisionId": "doc-r1"})
        if path == "/v1/presentations" and request.method == "POST":
            return httpx.Response(
                200,
                json={"presentationId": "slides-1", "slides": [{"objectId": "page-1"}]},
            )
        if path == "/v1/presentations/slides-1:batchUpdate":
            body = json.loads(request.content)
            assert len(body["requests"]) == 4
            return httpx.Response(200, json={})
        if path == "/v1/presentations/slides-1" and request.method == "GET":
            return httpx.Response(200, json={"revisionId": "slides-r1"})
        if path.startswith("/drive/v3/files/") and request.method == "PATCH":
            assert json.loads(request.content)["appProperties"].get("veritasRequest")
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[-1]})
        if path == "/gmail/v1/users/me/messages" and request.method == "GET":
            return httpx.Response(200, json={"messages": []})
        if path == "/gmail/v1/users/me/drafts" and request.method == "POST":
            assert json.loads(request.content)["message"]["raw"]
            return httpx.Response(200, json={"id": "draft-1", "message": {"id": "msg-1"}})
        if path == "/gmail/v1/users/me/messages/msg-1":
            return httpx.Response(200, json={"id": "msg-1", "historyId": "history-1"})
        if path == "/tasks/v1/users/@me/lists" and request.method == "GET":
            return httpx.Response(200, json={"items": []})
        if path == "/tasks/v1/users/@me/lists" and request.method == "POST":
            return httpx.Response(200, json={"id": "list-1", "title": "Veritas"})
        if path == "/tasks/v1/lists/list-1/tasks" and request.method == "GET":
            return httpx.Response(200, json={"items": []})
        if path == "/tasks/v1/lists/list-1/tasks" and request.method == "POST":
            body = json.loads(request.content)
            assert body["title"].startswith("[veritas:")
            assert "Customer churn is 9%." in body["notes"]
            return httpx.Response(200, json={"id": "task-1", "etag": "task-r1"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            writer = GoogleWorkspacePacketWriter("access", "owner@example.test", client)
            document = await writer.materialize(_draft(ArtifactKind.GOOGLE_DOC), "request-1")
            slides = await writer.materialize(_draft(ArtifactKind.GOOGLE_SLIDES), "request-2")
            gmail = await writer.materialize(_draft(ArtifactKind.GMAIL), "request-3")
            task = await writer.materialize(_draft(ArtifactKind.GOOGLE_TASK), "request-4")

        assert document.resource_id == "doc-1"
        assert document.revision_id == "doc-r1"
        assert document.anchors["claim-1"].endswith("#claim-slot-1")
        assert slides.resource_id == "slides-1"
        assert slides.anchors["claim-1"].startswith("workspace://slides/slides-1#v_")
        assert gmail.resource_id == "msg-1"
        assert gmail.revision_id == "history-1"
        assert task.resource_id == "task-1"
        assert task.container_id == "list-1"

    asyncio.run(scenario())
    assert all(request.headers["Authorization"] == "Bearer access" for request in seen)


def test_google_packet_writer_reuses_idempotent_artifacts_without_creating_duplicates() -> None:
    create_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            create_requests.append(path)
        if path == "/drive/v3/files":
            mime = request.url.params["q"]
            return httpx.Response(
                200,
                json={
                    "files": [{"id": "existing-doc" if "document" in mime else "existing-slides"}]
                },
            )
        if path == "/v1/documents/existing-doc":
            return httpx.Response(200, json={"revisionId": "doc-r2"})
        if path == "/v1/presentations/existing-slides":
            return httpx.Response(200, json={"revisionId": "slides-r2"})
        if path == "/gmail/v1/users/me/messages":
            return httpx.Response(200, json={"messages": [{"id": "existing-message"}]})
        if path == "/gmail/v1/users/me/messages/existing-message":
            return httpx.Response(200, json={"historyId": "history-r2"})
        if path == "/tasks/v1/users/@me/lists":
            return httpx.Response(200, json={"items": [{"id": "list-1", "title": "Veritas"}]})
        if path == "/tasks/v1/lists/list-1/tasks":
            marker = request.url.params.get("unused")
            del marker
            return httpx.Response(200, json={"items": []})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            writer = GoogleWorkspacePacketWriter("access", "owner@example.test", client)
            assert (
                await writer.materialize(_draft(ArtifactKind.GOOGLE_DOC), "request-1")
            ).resource_id == "existing-doc"
            assert (
                await writer.materialize(_draft(ArtifactKind.GOOGLE_SLIDES), "request-2")
            ).resource_id == "existing-slides"
            assert (
                await writer.materialize(_draft(ArtifactKind.GMAIL), "request-3")
            ).resource_id == "existing-message"

    asyncio.run(scenario())
    assert create_requests == []


def test_google_packet_writer_fails_closed_on_workspace_errors() -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                503,
                json={
                    "error": {
                        "message": "secret detail",
                        "errors": [{"reason": "rateLimitExceeded"}],
                    }
                },
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            writer = GoogleWorkspacePacketWriter("access", "owner@example.test", client)
            with pytest.raises(WorkspacePacketWriteError, match="status 503") as raised:
                await writer.materialize(_draft(ArtifactKind.GOOGLE_DOC), "request-1")
            assert "secret detail" not in str(raised.value)
            assert "rateLimitExceeded" in str(raised.value)

    asyncio.run(scenario())
