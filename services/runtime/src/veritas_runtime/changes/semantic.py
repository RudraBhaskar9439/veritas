import hashlib
import json
import math
import unicodedata
from decimal import Decimal

from veritas_runtime.changes.models import DeltaKind, EvidenceCapture, EvidenceSnapshot, JsonValue


class InvalidEvidenceCapture(ValueError):
    """Evidence cannot be canonicalized without changing or losing meaning."""


def canonical_capture(capture: EvidenceCapture) -> bytes:
    return _canonical_json(capture.model_dump(mode="json", by_alias=True))


def content_hash(capture: EvidenceCapture) -> str:
    return hashlib.sha256(canonical_capture(capture)).hexdigest()


def semantic_hash(capture: EvidenceCapture) -> str:
    semantic = {
        "mimeType": capture.mime_type,
        "resourceId": capture.resource_id,
        "evidence": _normalize(capture.evidence),
    }
    return hashlib.sha256(_canonical_json(semantic)).hexdigest()


def classify_delta(
    current_content_hash: str,
    current_semantic_hash: str,
    previous: EvidenceSnapshot | None,
) -> DeltaKind:
    if previous is None:
        return DeltaKind.BASELINE
    if current_content_hash == previous.content_hash:
        return DeltaKind.DUPLICATE
    if current_semantic_hash == previous.semantic_hash:
        return DeltaKind.COSMETIC
    return DeltaKind.MEANINGFUL


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as error:
        raise InvalidEvidenceCapture("Evidence contains a non-canonical value") from error


def _normalize(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidEvidenceCapture("Evidence numbers must be finite")
        normalized = Decimal(str(value)).normalize()
        return int(normalized) if normalized == normalized.to_integral() else float(normalized)
    return value
