import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from veritas_runtime.email_tasks import gemini as gemini_module
from veritas_runtime.email_tasks import security as security_module
from veritas_runtime.email_tasks.gemini import EmailTaskExtractionError, GeminiEmailTaskGateway
from veritas_runtime.email_tasks.models import (
    EmailTaskDisposition,
    GeminiEmailTaskPayload,
    GoogleTaskState,
    InboundEmail,
)
from veritas_runtime.email_tasks.security import (
    GooglePubSubIdentityVerifier,
    InvalidPubSubIdentity,
)

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _email() -> InboundEmail:
    return InboundEmail(
        message_id="message-1",
        thread_id="thread-1",
        history_id="101",
        sender="customer@example.com",
        recipient="operator@example.com",
        subject_line="Move onboarding [VX-A1B2C3D4E5F6]",
        body="Please move onboarding to Friday at 3 PM.",
        received_at=NOW,
    )


class FakeModels:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.prompt = ""

    async def generate_content(self, **kwargs):  # type: ignore[no-untyped-def]
        if self.error is not None:
            raise self.error
        self.prompt = kwargs["contents"][0].parts[0].text
        return self.response


class FakeGeminiClient:
    def __init__(self, models: FakeModels) -> None:
        self.aio = SimpleNamespace(models=models, aclose=self._aclose)
        self.closed = False

    async def _aclose(self) -> None:
        self.closed = True

    def close(self) -> None:
        self.closed = True


def _payload() -> GeminiEmailTaskPayload:
    return GeminiEmailTaskPayload(
        disposition=EmailTaskDisposition.UPDATE,
        proposed_title="Confirm Acme onboarding for Friday",
        proposed_note="Customer confirmed the Friday onboarding time.",
        rationale="The customer supplied a clear reversible scheduling update.",
        confidence=0.98,
        risk_flags=(),
    )


def _task() -> GoogleTaskState:
    return GoogleTaskState(
        task_id="task-1",
        title="Confirm onboarding",
        notes="Human note",
        etag="v1",
    )


def test_gemini_gateway_accepts_schema_or_json_and_fails_closed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        parsed_models = FakeModels(SimpleNamespace(parsed=_payload(), text=None))
        parsed_client = FakeGeminiClient(parsed_models)
        monkeypatch.setattr(gemini_module.genai, "Client", lambda **_: parsed_client)
        gateway = GeminiEmailTaskGateway("project-1", "us-central1", "gemini-3.5-flash")
        assert await gateway.extract(_email(), _task()) == _payload()
        assert "never with an AI label" in parsed_models.prompt
        await gateway.close()
        assert parsed_client.closed

        json_models = FakeModels(
            SimpleNamespace(parsed=None, text=_payload().model_dump_json(by_alias=True))
        )
        monkeypatch.setattr(
            gemini_module.genai,
            "Client",
            lambda **_: FakeGeminiClient(json_models),
        )
        assert await GeminiEmailTaskGateway("p", "l", "m").extract(_email(), _task()) == _payload()

        for response, message in (
            (SimpleNamespace(parsed=None, text="not-json"), "invalid email contract"),
            (SimpleNamespace(parsed=None, text=None), "no email instruction"),
        ):
            monkeypatch.setattr(
                gemini_module.genai,
                "Client",
                lambda response=response, **_: FakeGeminiClient(FakeModels(response)),
            )
            with pytest.raises(EmailTaskExtractionError, match=message):
                await GeminiEmailTaskGateway("p", "l", "m").extract(_email(), _task())

        monkeypatch.setattr(
            gemini_module.genai,
            "Client",
            lambda **_: FakeGeminiClient(FakeModels(error=RuntimeError("offline"))),
        )
        with pytest.raises(EmailTaskExtractionError, match="unavailable"):
            await GeminiEmailTaskGateway("p", "l", "m").extract(_email(), _task())

    with pytest.raises(ValueError, match="configuration is incomplete"):
        GeminiEmailTaskGateway("", "us-central1", "model")
    asyncio.run(scenario())


def test_pubsub_oidc_identity_is_audience_and_service_account_bound(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    verifier = GooglePubSubIdentityVerifier(
        "https://ingress.example.com",
        "gmail-push@example-project.iam.gserviceaccount.com",
    )

    async def scenario() -> None:
        monkeypatch.setattr(
            security_module.id_token,
            "verify_oauth2_token",
            lambda token, request, audience: {
                "email": "gmail-push@example-project.iam.gserviceaccount.com",
                "email_verified": True,
                "aud": audience,
            },
        )
        await verifier.verify("Bearer signed-token")

        with pytest.raises(InvalidPubSubIdentity, match="bearer identity is required"):
            await verifier.verify(None)

        monkeypatch.setattr(
            security_module.id_token,
            "verify_oauth2_token",
            lambda *args: {"email": "attacker@example.com", "email_verified": True},
        )
        with pytest.raises(InvalidPubSubIdentity, match="not authorized"):
            await verifier.verify("Bearer wrong-identity")

        monkeypatch.setattr(
            security_module.id_token,
            "verify_oauth2_token",
            lambda *args: (_ for _ in ()).throw(ValueError("bad token")),
        )
        with pytest.raises(InvalidPubSubIdentity, match="identity is invalid"):
            await verifier.verify("Bearer invalid")

    with pytest.raises(ValueError, match="configuration is invalid"):
        GooglePubSubIdentityVerifier("http://not-secure", "not-an-email")
    asyncio.run(scenario())
