from veritas_runtime.security import security_headers, trusted_request_id


def test_request_ids_are_bounded_and_untrusted_values_are_replaced() -> None:
    assert trusted_request_id("incident-042:repair/1") == "incident-042:repair/1"
    assert trusted_request_id("line\nbreak") != "line\nbreak"
    assert trusted_request_id("x" * 129) != "x" * 129
    assert trusted_request_id(None)


def test_security_headers_add_hsts_only_on_secure_transport() -> None:
    local = security_headers(transport_secure=False)
    secure = security_headers(transport_secure=True)
    assert "Strict-Transport-Security" not in local
    assert secure["Strict-Transport-Security"].startswith("max-age=31536000")
    assert secure["Content-Security-Policy"].startswith("default-src 'none'")
    assert secure["Permissions-Policy"] == "camera=(), microphone=(), geolocation=(), payment=()"
