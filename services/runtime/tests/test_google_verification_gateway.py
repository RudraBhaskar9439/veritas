import asyncio
import base64
from email.message import EmailMessage

import httpx

from repair_support import canonical_repair_context
from veritas_runtime.packets.models import ArtifactMutability, ArtifactRecord
from veritas_runtime.repairs.models import RepairOperation
from veritas_runtime.repairs.planner import TypedRepairPlanner
from veritas_runtime.verification.google import GoogleWorkspaceVerificationGateway


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


def test_docs_verification_rereads_anchor_and_excludes_it_from_protected_hash() -> None:
    steps = tuple(step for step in _steps() if step.artifact_id == "artifact-board-memo")
    artifact = ArtifactRecord(
        artifact_id=steps[0].artifact_id,
        kind=steps[0].artifact_kind,
        resource_id=steps[0].resource_id,
        base_revision_id=steps[0].base_revision_id,
        mutability=ArtifactMutability.EDITABLE,
    )
    repaired = False

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        statements = tuple(
            step.proposed_statement if repaired else step.before_statement for step in steps
        )
        human = "CFO: preserve this paragraph byte-for-byte."
        first_start = 1
        first_end = first_start + len(statements[0])
        human_start = first_end
        human_end = human_start + len(human)
        second_start = human_end
        second_end = second_start + len(statements[1])
        return httpx.Response(
            200,
            json={
                "revisionId": "doc-v2" if repaired else "doc-v1",
                "tabs": [
                    {
                        "documentTab": {
                            "namedRanges": {
                                steps[0].anchor: {
                                    "namedRanges": [
                                        {
                                            "ranges": [
                                                {"startIndex": first_start, "endIndex": first_end}
                                            ]
                                        }
                                    ]
                                },
                                steps[1].anchor: {
                                    "namedRanges": [
                                        {
                                            "ranges": [
                                                {
                                                    "startIndex": second_start,
                                                    "endIndex": second_end,
                                                }
                                            ]
                                        }
                                    ]
                                },
                            },
                            "body": {
                                "content": [
                                    {
                                        "paragraph": {
                                            "elements": [
                                                {
                                                    "startIndex": first_start,
                                                    "endIndex": first_end,
                                                    "textRun": {"content": statements[0]},
                                                },
                                                {
                                                    "startIndex": human_start,
                                                    "endIndex": human_end,
                                                    "textRun": {"content": human},
                                                },
                                                {
                                                    "startIndex": second_start,
                                                    "endIndex": second_end,
                                                    "textRun": {"content": statements[1]},
                                                },
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

    async def scenario() -> None:
        nonlocal repaired
        gateway = GoogleWorkspaceVerificationGateway(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        before = await gateway.protected_state(
            "token",
            artifact,
            tuple(step.anchor for step in steps),
            tuple(step.before_statement for step in steps),
        )
        repaired = True
        observed = await gateway.read_registered(
            "token",
            artifact,
            steps[0].anchor,
            steps[0].proposed_statement,
            steps[0].before_statement,
        )
        after = await gateway.protected_state(
            "token",
            artifact,
            tuple(step.anchor for step in steps),
            tuple(step.proposed_statement for step in steps),
        )
        assert observed.statement == steps[0].proposed_statement
        assert before.protected_content_hash == after.protected_content_hash

    asyncio.run(scenario())


def test_task_protection_hash_preserves_human_notes_across_registered_repair() -> None:
    step = next(step for step in _steps() if step.artifact_id == "artifact-acquisition-task")
    artifact = ArtifactRecord(
        artifact_id=step.artifact_id,
        kind=step.artifact_kind,
        resource_id=step.resource_id,
        container_id=step.container_id,
        base_revision_id=step.base_revision_id,
        mutability=ArtifactMutability.EDITABLE,
    )
    repaired = False

    def handler(request: httpx.Request) -> httpx.Response:
        statement = step.proposed_statement if repaired else step.before_statement
        return httpx.Response(
            200,
            json={
                "etag": '"task-v2"' if repaired else '"task-v1"',
                "notes": f"Owner: Growth\n{statement}\nKeep this human note.",
            },
        )

    async def scenario() -> None:
        nonlocal repaired
        gateway = GoogleWorkspaceVerificationGateway(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        before = await gateway.protected_state(
            "token", artifact, (step.anchor,), (step.before_statement,)
        )
        repaired = True
        after = await gateway.protected_state(
            "token", artifact, (step.anchor,), (step.proposed_statement,)
        )
        assert before.protected_content_hash == after.protected_content_hash

    asyncio.run(scenario())


def test_correction_verification_reads_the_created_draft_without_sending() -> None:
    step = next(
        step for step in _steps() if step.operation == RepairOperation.CREATE_CORRECTION_DRAFT
    )
    draft = EmailMessage()
    draft["To"] = "investor@example.test"
    draft["Subject"] = "Correction: Q3 Investor Update"
    draft.set_content(f"Corrected: {step.proposed_statement}\nThis message has not been sent.")
    raw = base64.urlsafe_b64encode(draft.as_bytes()).decode().rstrip("=")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert not request.url.path.endswith("/send")
        return httpx.Response(
            200,
            json={
                "id": "draft-1",
                "message": {
                    "id": "draft-message-1",
                    "historyId": "history-2",
                    "raw": raw,
                },
            },
        )

    async def scenario() -> None:
        gateway = GoogleWorkspaceVerificationGateway(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        observed = await gateway.read_correction("token", step, "draft-1")
        assert observed.resource_id == "draft-1"
        assert observed.statement == step.proposed_statement

    asyncio.run(scenario())


def test_slides_verification_checks_registered_shape_and_protects_other_shapes() -> None:
    step = next(step for step in _steps() if step.artifact_id == "artifact-exec-deck")
    artifact = ArtifactRecord(
        artifact_id=step.artifact_id,
        kind=step.artifact_kind,
        resource_id=step.resource_id,
        base_revision_id=step.base_revision_id,
        mutability=ArtifactMutability.EDITABLE,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "revisionId": "slides-v2",
                "slides": [
                    {
                        "pageElements": [
                            {
                                "objectId": step.anchor,
                                "shape": {
                                    "text": {
                                        "textElements": [
                                            {
                                                "textRun": {
                                                    "content": f"{step.proposed_statement}\n"
                                                }
                                            }
                                        ]
                                    }
                                },
                            },
                            {
                                "objectId": "human-shape",
                                "shape": {
                                    "text": {
                                        "textElements": [
                                            {"textRun": {"content": "Founder commentary\n"}}
                                        ]
                                    }
                                },
                            },
                        ]
                    }
                ],
            },
        )

    async def scenario() -> None:
        gateway = GoogleWorkspaceVerificationGateway(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        observed = await gateway.read_registered(
            "token",
            artifact,
            step.anchor,
            step.proposed_statement,
            step.before_statement,
        )
        protected = await gateway.protected_state(
            "token", artifact, (step.anchor,), (step.proposed_statement,)
        )
        assert observed.statement == step.proposed_statement
        assert protected.revision_id == "slides-v2"
        assert len(protected.protected_content_hash) == 64

    asyncio.run(scenario())
