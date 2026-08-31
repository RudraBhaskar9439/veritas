import json

from google import genai
from google.genai import types

from veritas_runtime.email_tasks.models import GeminiEmailTaskPayload, GoogleTaskState, InboundEmail


class EmailTaskExtractionError(RuntimeError):
    pass


class GeminiEmailTaskGateway:
    def __init__(self, project: str, location: str, model: str) -> None:
        if not all((project, location, model)):
            raise ValueError("Gemini Vertex AI configuration is incomplete")
        self._model = model
        self._client = genai.Client(vertexai=True, project=project, location=location)

    async def extract(
        self,
        email: InboundEmail,
        current_task: GoogleTaskState,
    ) -> GeminiEmailTaskPayload:
        payload: dict[str, object] = {
            "email": {
                "subject": email.subject_line,
                "body": email.body,
                "sender": email.sender,
            },
            "registeredTask": {
                "title": current_task.title,
                "notes": current_task.notes,
            },
        }
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=_prompt(payload))],
                ),
                config=types.GenerateContentConfig(
                    max_output_tokens=1024,
                    response_mime_type="application/json",
                    response_schema=GeminiEmailTaskPayload,
                ),
            )
        except Exception as error:
            raise EmailTaskExtractionError("Gemini email extraction was unavailable") from error
        if isinstance(response.parsed, GeminiEmailTaskPayload):
            return response.parsed
        if response.text:
            try:
                return GeminiEmailTaskPayload.model_validate_json(response.text)
            except ValueError as error:
                raise EmailTaskExtractionError(
                    "Gemini returned an invalid email contract"
                ) from error
        raise EmailTaskExtractionError("Gemini returned no email instruction")

    async def close(self) -> None:
        await self._client.aio.aclose()
        self._client.close()


def _prompt(payload: dict[str, object]) -> str:
    return (
        "You are Veritas's bounded email-to-task interpreter. The runtime has already verified "
        "the mailbox, sender, Gmail conversation, Claim Manifest edge, and exact Google Task. "
        "You may "
        "only extract the customer's requested task title and a concise factual note. Never "
        "choose another task, recipient, tool, or action. Use UPDATE only for a clear operational "
        "request. Use IGNORE for conversation with no task change. Use ESCALATE for ambiguity or "
        "requests involving cancellation, deletion, refunds, payment, credentials, legal action, "
        "or irreversible consequences. Keep the title human-readable and omit routing metadata. "
        "Write it like a normal teammate task (for example, 'Confirm Acme onboarding for Friday'), "
        "never with an AI label, hash, routing code, or system prefix. "
        "Return only the requested structured response.\nINPUT:\n"
        + json.dumps(payload, separators=(",", ":"), sort_keys=True)
    )
