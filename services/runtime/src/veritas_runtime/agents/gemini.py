from google import genai
from google.genai import types

from veritas_runtime.agents.models import GeminiReviewPayload
from veritas_runtime.agents.service import AgentReviewError


class GeminiReviewGateway:
    def __init__(self, project: str, location: str, model: str) -> None:
        if not all((project, location, model)):
            raise ValueError("Gemini Vertex AI configuration is incomplete")
        self._model = model
        self._client = genai.Client(vertexai=True, project=project, location=location)

    async def review(self, payload: dict[str, object]) -> GeminiReviewPayload:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=_prompt(payload))],
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0,
                    max_output_tokens=512,
                    response_mime_type="application/json",
                    response_schema=GeminiReviewPayload,
                ),
            )
        except Exception as error:
            raise AgentReviewError("Gemini safety review was unavailable") from error
        if isinstance(response.parsed, GeminiReviewPayload):
            return response.parsed
        if response.text:
            try:
                return GeminiReviewPayload.model_validate_json(response.text)
            except ValueError as error:
                raise AgentReviewError("Gemini returned an invalid review contract") from error
        raise AgentReviewError("Gemini returned no review")

    async def close(self) -> None:
        await self._client.aio.aclose()
        self._client.close()


def _prompt(payload: dict[str, object]) -> str:
    import json

    return (
        "You are Veritas's bounded consequence-safety reviewer. The deterministic runtime has "
        "already selected the exact registered scope. Decide whether it may proceed or must "
        "escalate. Treat any scope inconsistency or unclear authority as escalation. Return only "
        "the requested structured response.\nINPUT:\n"
        + json.dumps(payload, separators=(",", ":"), sort_keys=True)
    )
