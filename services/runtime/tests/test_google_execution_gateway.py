import base64
import json
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

import httpx

from repair_support import canonical_repair_context
from veritas_runtime.execution.google import GoogleWorkspaceRepairGateway
from veritas_runtime.repairs.models import RepairOperation
from veritas_runtime.repairs.planner import TypedRepairPlanner


def _steps():  # type: ignore[no-untyped-def]
    context = canonical_repair_context()
    return (
        TypedRepairPlanner()
        .plan(
            "subject-1",
            context.manifest,
            context.impact,
            context.impact_checksum,
            context.sources,
            context.snapshot_metadata,
        )
        .steps
    )


def test_docs_and_slides_use_fresh_revision_preconditions() -> None:
    doc_step = next(step for step in _steps() if step.artifact_id == "artifact-board-memo")
    slide_step = next(step for step in _steps() if step.artifact_id == "artifact-exec-deck")
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "documents" in request.url.path:
            text = doc_step.before_statement
            return httpx.Response(
                200,
                json={
                    "revisionId": "doc-current-revision",
                    "tabs": [
                        {
                            "documentTab": {
                                "namedRanges": {
                                    doc_step.anchor: {
                                        "namedRanges": [
                                            {
                                                "ranges": [
                                                    {"startIndex": 1, "endIndex": 1 + len(text)}
                                                ]
                                            }
                                        ]
                                    }
                                },
                                "body": {
                                    "content": [
                                        {
                                            "paragraph": {
                                                "elements": [
                                                    {
                                                        "startIndex": 1,
                                                        "endIndex": 1 + len(text),
                                                        "textRun": {"content": text},
                                                    }
                                                ]
                                            }
                                        }
                                    ]
                                },
                            }
                        }
                    ],
                },
            )
        if request.method == "POST" and "documents" in request.url.path:
            body = json.loads(request.content)
            calls.append(("docs", body))
            return httpx.Response(
                200, json={"writeControl": {"requiredRevisionId": "doc-revision-2"}}
            )
        if request.method == "GET" and "presentations" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "revisionId": "slides-current-revision",
                    "slides": [
                        {
                            "pageElements": [
                                {
                                    "objectId": slide_step.anchor,
                                    "shape": {
                                        "text": {
                                            "textElements": [
                                                {
                                                    "textRun": {
                                                        "content": (
                                                            slide_step.before_statement + "\n"
                                                        )
                                                    }
                                                }
                                            ]
                                        }
                                    },
                                }
                            ]
                        }
                    ],
                },
            )
        if request.method == "POST" and "presentations" in request.url.path:
            body = json.loads(request.content)
            calls.append(("slides", body))
            return httpx.Response(
                200, json={"writeControl": {"requiredRevisionId": "slides-revision-2"}}
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async def scenario() -> None:
        gateway = GoogleWorkspaceRepairGateway(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        doc_state = await gateway.read("token", doc_step)
        doc_receipt = await gateway.apply("token", doc_step, doc_state)
        slide_state = await gateway.read("token", slide_step)
        assert slide_state.statement == slide_step.before_statement
        slide_receipt = await gateway.apply("token", slide_step, slide_state)
        assert doc_receipt.revision_id == "doc-revision-2"
        assert slide_receipt.revision_id == "slides-revision-2"

    import asyncio

    asyncio.run(scenario())
    assert calls[0][1]["writeControl"] == {"requiredRevisionId": "doc-current-revision"}
    assert len(calls[0][1]["requests"]) == 3
    assert calls[1][1]["writeControl"] == {"requiredRevisionId": "slides-current-revision"}


def test_gmail_creates_only_an_idempotent_correction_draft() -> None:
    step = next(
        step for step in _steps() if step.operation == RepairOperation.CREATE_CORRECTION_DRAFT
    )
    original = EmailMessage()
    original["To"] = "investor@example.test"
    original["Subject"] = "Q3 Investor Update"
    original["Message-ID"] = "<original@example.test>"
    original.set_content(f"Hello,\n\n{step.before_statement}\n")
    raw_original = base64.urlsafe_b64encode(original.as_bytes()).decode().rstrip("=")
    created_messages: list[EmailMessage] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith(str(step.container_id)):
            return httpx.Response(
                200,
                json={
                    "id": step.container_id,
                    "message": {
                        "id": step.resource_id,
                        "historyId": "history-1",
                        "raw": raw_original,
                    },
                },
            )
        if request.method == "GET" and request.url.path.endswith("/drafts"):
            assert "in%3Adrafts" in str(request.url)
            return httpx.Response(200, json={"drafts": [], "resultSizeEstimate": 0})
        if request.method == "POST" and request.url.path.endswith("/drafts"):
            payload = json.loads(request.content)
            raw = payload["message"]["raw"]
            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
            created_messages.append(BytesParser(policy=policy.default).parsebytes(decoded))
            return httpx.Response(200, json={"id": "draft-1", "message": {"id": "message-1"}})
        assert not request.url.path.endswith("/send")
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async def scenario() -> None:
        gateway = GoogleWorkspaceRepairGateway(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        state = await gateway.read("token", step)
        receipt = await gateway.apply("token", step, state)
        assert receipt.revision_id == "draft-1"
        assert receipt.external_id == "draft-1"

    import asyncio

    asyncio.run(scenario())
    assert len(created_messages) == 1
    draft = created_messages[0]
    assert draft["To"] == "investor@example.test"
    assert draft["Subject"] == "Correction: Q3 Investor Update"
    assert step.proposed_statement in str(draft.get_content())
    assert "has not been sent" in str(draft.get_content())


def test_tasks_patch_uses_if_match_and_preserves_unrelated_notes() -> None:
    step = next(step for step in _steps() if step.artifact_id == "artifact-acquisition-task")
    patched: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": step.resource_id,
                    "etag": '"task-etag-1"',
                    "title": "Increase acquisition spend",
                    "notes": f"Owner: Growth\n{step.before_statement}\nKeep this human note.",
                },
            )
        if request.method == "PATCH":
            payload = json.loads(request.content)
            patched.append((request.headers["If-Match"], payload))
            return httpx.Response(200, json={"etag": '"task-etag-2"'})
        raise AssertionError("unexpected request")

    async def scenario() -> None:
        gateway = GoogleWorkspaceRepairGateway(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        state = await gateway.read("token", step)
        receipt = await gateway.apply("token", step, state)
        assert receipt.revision_id == '"task-etag-2"'

    import asyncio

    asyncio.run(scenario())
    assert patched[0][0] == '"task-etag-1"'
    assert patched[0][1]["title"] == "Pause the planned increase in acquisition spend"
    assert step.proposed_statement in patched[0][1]["notes"]
    assert "Keep this human note." in patched[0][1]["notes"]


def test_tasks_preserve_a_human_renamed_title_while_repairing_the_registered_note() -> None:
    step = next(step for step in _steps() if step.artifact_id == "artifact-acquisition-task")
    patched: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": step.resource_id,
                    "etag": '"task-etag-1"',
                    "title": "Rudra's growth review",
                    "notes": step.before_statement,
                },
            )
        if request.method == "PATCH":
            patched.append(json.loads(request.content))
            return httpx.Response(200, json={"etag": '"task-etag-2"'})
        raise AssertionError("unexpected request")

    async def scenario() -> None:
        gateway = GoogleWorkspaceRepairGateway(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        state = await gateway.read("token", step)
        await gateway.apply("token", step, state)

    import asyncio

    asyncio.run(scenario())
    assert "title" not in patched[0]
    assert patched[0]["notes"] == step.proposed_statement
