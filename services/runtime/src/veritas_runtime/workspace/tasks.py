import re

_LEGACY_TITLE = re.compile(r"^\[veritas:[0-9a-f]{16}\]\s+", re.IGNORECASE)
_ACTION_PREFIXES = (
    "The company should ",
    "The team should ",
    "We should ",
    "You should ",
)


def natural_task_title(statement: str, fallback: str = "Review decision") -> str:
    """Render a registered decision as a concise, human-facing task title."""

    candidate = statement.strip()
    for prefix in _ACTION_PREFIXES:
        if candidate.casefold().startswith(prefix.casefold()):
            candidate = candidate[len(prefix) :]
            break
    candidate = candidate.rstrip(".!?").strip()
    if not candidate:
        candidate = fallback.strip().rstrip(".!?") or "Review decision"
    return candidate[:1].upper() + candidate[1:]


def task_reference(key: str) -> str:
    return f"VX-{key[:16].upper()}"


def task_tracking_footer(artifact_id: str, key: str) -> str:
    return f"Synced by Veritas\nWorkflow: {artifact_id}\nReference: {task_reference(key)}"


def task_notes(statements: tuple[str, ...], artifact_id: str, key: str) -> str:
    body = "\n\n".join(statement.strip() for statement in statements if statement.strip())
    return f"{body}\n\n{task_tracking_footer(artifact_id, key)}"


def has_task_reference(notes: str, key: str) -> bool:
    return f"Reference: {task_reference(key)}" in notes.splitlines()


def has_task_workflow(notes: str, artifact_id: str) -> bool:
    return f"Workflow: {artifact_id}" in notes.splitlines()


def is_legacy_task_title(title: str, expected_title: str | None = None) -> bool:
    match = _LEGACY_TITLE.match(title)
    if match is None:
        return False
    return expected_title is None or title[match.end() :] == expected_title
