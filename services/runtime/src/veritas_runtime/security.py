import re
from uuid import uuid4

_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def trusted_request_id(value: str | None) -> str:
    """Accept bounded printable correlation IDs and replace unsafe input."""

    if value is not None and _REQUEST_ID.fullmatch(value):
        return value
    return str(uuid4())


def security_headers(*, transport_secure: bool) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }
    if transport_secure:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return headers
