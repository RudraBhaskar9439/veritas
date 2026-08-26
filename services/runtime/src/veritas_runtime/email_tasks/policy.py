import hashlib
import re
from email.utils import parseaddr


class InvalidEmailAddress(ValueError):
    pass


def normalize_email(value: str) -> str:
    _, address = parseaddr(value.strip())
    if not address or address.count("@") != 1:
        raise InvalidEmailAddress("A valid email address is required")
    local, domain = address.rsplit("@", 1)
    if not local or not domain or "." not in domain or any(char.isspace() for char in address):
        raise InvalidEmailAddress("A valid email address is required")
    return f"{local.lower()}@{domain.lower()}"


def workflow_routing_key(
    subject: str,
    packet_id: str,
    claim_id: str,
    artifact_id: str,
    authorized_sender: str,
) -> str:
    identity = ":".join(
        (subject, packet_id, claim_id, artifact_id, normalize_email(authorized_sender))
    )
    return f"VX-{hashlib.sha256(identity.encode()).hexdigest()[:12].upper()}"


def routes_to_workflow(subject_line: str, routing_key: str) -> bool:
    return f"[{routing_key}]" in subject_line


_HIGH_RISK = re.compile(
    r"\b(cancel|delete|refund|payment|bank|credentials?|password|terminate|legal|wire)\b",
    flags=re.IGNORECASE,
)


def deterministic_risk_flags(subject_line: str, body: str) -> tuple[str, ...]:
    matches = sorted(
        {
            match.group(0).lower().removesuffix("s")
            for match in _HIGH_RISK.finditer(subject_line + "\n" + body)
        }
    )
    return tuple(f"sensitive:{value}" for value in matches)
