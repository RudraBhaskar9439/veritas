import asyncio
import base64
import json
from datetime import UTC, datetime

import httpx
import pytest

from veritas_runtime.email_tasks.google import (
    EmailTaskPreconditionFailed,
    GoogleGmailTaskGateway,
)

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_google_gateway_watches_reads_history_and_updates_with_etag() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/watch"):
            return httpx.Response(
                200,
                json={"historyId": "10", "expiration": "1787742000000"},
            )
        if request.url.path.endswith("/history"):
            return httpx.Response(
                200,
                json={
                    "historyId": "12",
                    "history": [
                        {"messagesAdded": [{"message": {"id": "message-1", "labelIds": ["INBOX"]}}]}
                    ],
                },
            )
        if request.url.path.endswith("/messages/message-1"):
            return httpx.Response(
                200,
                json={
                    "id": "message-1",
                    "threadId": "thread-1",
                    "internalDate": "1787738400000",
                    "payload": {
                        "mimeType": "multipart/alternative",
                        "headers": [
                            {"name": "From", "value": "Customer <customer@example.com>"},
                            {"name": "To", "value": "operator@example.com"},
                            {
                                "name": "Subject",
                                "value": "Move installation [VX-ABCDEF123456]",
                            },
                        ],
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {"data": _encoded("Please move it to Friday.")},
                            }
                        ],
                    },
                },
            )
        if request.method == "GET" and "/tasks/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "id": "task-1",
                    "title": "Install Thursday",
                    "notes": "Human note",
                    "etag": "v1",
                },
            )
        if request.method == "PATCH" and "/tasks/" in request.url.path:
            assert request.headers["if-match"] == "v1"
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "id": "task-1",
                    "title": body["title"],
                    "notes": body["notes"],
                    "etag": "v2",
                },
            )
        return httpx.Response(404)

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = GoogleGmailTaskGateway(
            client,
            gmail_root="https://gmail.test/gmail/v1",
            tasks_root="https://tasks.test/tasks/v1",
        )
        stream = await gateway.start_watch(
            "subject-1",
            "operator@example.com",
            "token",
            "projects/project-1/topics/gmail",
            NOW,
        )
        assert stream.history_id == "10"
        page = await gateway.history_since("token", stream.history_id)
        assert page.message_ids == ("message-1",)
        email = await gateway.get_email("token", "message-1", page.history_id)
        assert email.sender == "customer@example.com"
        assert email.body == "Please move it to Friday."
        task = await gateway.get_task("token", "list-1", "task-1")
        updated = await gateway.update_task(
            "token", "list-1", task, "Install Friday", "Human note\n\nVerified"
        )
        assert updated.etag == "v2"
        assert calls[0].headers["authorization"] == "Bearer token"
        await client.aclose()

    asyncio.run(scenario())


def test_google_task_precondition_conflict_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(412, json={"error": "precondition"})

    async def scenario() -> None:
        from veritas_runtime.email_tasks.models import GoogleTaskState

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = GoogleGmailTaskGateway(client, tasks_root="https://tasks.test/tasks/v1")
        with pytest.raises(EmailTaskPreconditionFailed, match="no overwrite"):
            await gateway.update_task(
                "token",
                "list-1",
                GoogleTaskState(task_id="task-1", title="Old", etag="v1"),
                "New",
                "Notes",
            )
        await client.aclose()

    asyncio.run(scenario())
