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
                    max_output_tokens=2048,
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
        "escalate. PROCEED means hand the plan to the deterministic execution engine; it does "
        "not authorize approval-gated steps. The engine will pause those steps until a human "
        "approves them, so approvalRequiredSteps greater than zero and an awaitingApproval plan "
        "state are expected safety controls, not reasons to escalate. Draft-only steps are also "
        "expected and preserve immutable originals. Escalate only for an internal contradiction, "
        "a scope mismatch, an unregistered action, or a missing authority boundary. A lineage-"
        "affected claim can be semantically unchanged when its deterministic transformation "
        "reproduces the registered statement; those claims are intentionally absent from repair "
        "steps and are not a contradiction. Return only the requested structured response."
        "\nINPUT:\n" + json.dumps(payload, separators=(",", ":"), sort_keys=True)
    )
