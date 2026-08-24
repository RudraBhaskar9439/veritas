from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from fastapi.responses import JSONResponse, RedirectResponse

from veritas_runtime.auth.oauth import OAuthExchangeError
from veritas_runtime.auth.service import GoogleConnectionService, InvalidAuthorizationAttempt
from veritas_runtime.auth.sessions import (
    ApplicationSessionCodec,
    InvalidApplicationSession,
    SessionPrincipal,
)
from veritas_runtime.auth.storage import CredentialIntegrityError
from veritas_runtime.workspace.contracts import CAPABILITY_SCOPES, REQUIRED_WORKSPACE_SCOPES

LOCAL_COOKIE_NAME = "veritas_google_oauth"
PRODUCTION_COOKIE_NAME = "__Host-veritas_google_oauth"
LOCAL_SESSION_COOKIE_NAME = "veritas_session"
PRODUCTION_SESSION_COOKIE_NAME = "__Host-veritas_session"


def create_google_auth_router(
    service: GoogleConnectionService | None,
    *,
    secure_cookie: bool,
    session_codec: ApplicationSessionCodec | None = None,
) -> APIRouter:
    router = APIRouter()
    cookie_name = PRODUCTION_COOKIE_NAME if secure_cookie else LOCAL_COOKIE_NAME
    session_cookie_name = (
        PRODUCTION_SESSION_COOKIE_NAME if secure_cookie else LOCAL_SESSION_COOKIE_NAME
    )

    @router.get("/api/v1/integrations/google/configuration", tags=["integrations"])
    async def google_configuration() -> dict[str, object]:
        return {
            "configured": service is not None,
            "capabilities": sorted(capability.value for capability in CAPABILITY_SCOPES),
            "scopeCount": len(REQUIRED_WORKSPACE_SCOPES),
        }

    @router.get("/api/v1/auth/google/start", tags=["auth"])
    async def google_start(
        return_to: str = Query(default="/integrations/google", alias="returnTo"),
    ) -> RedirectResponse:
        if service is None:
            raise HTTPException(status_code=503, detail="Google integration is not configured")
        try:
            authorization = await service.start(return_to)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        response = RedirectResponse(authorization.authorization_url, status_code=307)
        response.set_cookie(
            cookie_name,
            authorization.browser_ticket,
            httponly=True,
            secure=secure_cookie,
            samesite="lax",
            max_age=600,
            path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/api/v1/auth/google/callback", tags=["auth"])
    async def google_callback(
        state: str = Query(min_length=1),
        code: str | None = Query(default=None, min_length=1),
        error: str | None = Query(default=None, min_length=1),
        browser_ticket: str | None = Cookie(default=None, alias=cookie_name),
    ) -> Response:
        if service is None:
            raise HTTPException(status_code=503, detail="Google integration is not configured")
        if not browser_ticket:
            raise HTTPException(status_code=400, detail="OAuth browser ticket is missing")
        if error:
            try:
                return_to = await service.cancel(state, browser_ticket)
            except InvalidAuthorizationAttempt:
                return _cleared_error(cookie_name, secure_cookie)
            response = RedirectResponse(_with_google_status(return_to, "denied"), status_code=303)
            _clear_cookie(response, cookie_name, secure_cookie)
            response.headers["Cache-Control"] = "no-store"
            return response
        if code is None:
            return _cleared_error(cookie_name, secure_cookie)
        try:
            account = await service.complete(code, state, browser_ticket)
        except (InvalidAuthorizationAttempt, OAuthExchangeError, CredentialIntegrityError):
            return _cleared_error(cookie_name, secure_cookie)
        response = RedirectResponse(
            _with_google_status(account.return_to, "connected"), status_code=303
        )
        _clear_cookie(response, cookie_name, secure_cookie)
        if session_codec is not None:
            response.set_cookie(
                session_cookie_name,
                session_codec.encode(
                    SessionPrincipal(
                        subject=account.subject,
                        email=account.email,
                        issued_at=datetime.now(UTC),
                    )
                ),
                httponly=True,
                secure=secure_cookie,
                samesite="strict",
                max_age=43_200,
                path="/",
            )
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/api/v1/auth/session", tags=["auth"])
    async def current_session(
        session: str | None = Cookie(default=None, alias=session_cookie_name),
    ) -> dict[str, str]:
        if session_codec is None or session is None:
            raise HTTPException(status_code=401, detail="Application session is required")
        try:
            principal = session_codec.decode(session)
        except InvalidApplicationSession as error:
            raise HTTPException(status_code=401, detail="Application session is invalid") from error
        return {"subject": principal.subject, "email": principal.email}

    @router.post("/api/v1/auth/logout", status_code=204, tags=["auth"])
    async def logout() -> Response:
        response = Response(status_code=204, headers={"Cache-Control": "no-store"})
        response.delete_cookie(
            session_cookie_name,
            path="/",
            secure=secure_cookie,
            httponly=True,
            samesite="strict",
        )
        return response

    return router


def _with_google_status(return_to: str, status: str) -> str:
    parsed = urlsplit(return_to)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["google"] = status
    return urlunsplit(("", "", parsed.path, urlencode(query), parsed.fragment))


def _clear_cookie(response: Response, cookie_name: str, secure_cookie: bool) -> None:
    response.delete_cookie(cookie_name, path="/", secure=secure_cookie, httponly=True)


def _cleared_error(cookie_name: str, secure_cookie: bool) -> JSONResponse:
    response = JSONResponse(
        status_code=400,
        content={"detail": "Google connection could not be verified"},
        headers={"Cache-Control": "no-store"},
    )
    _clear_cookie(response, cookie_name, secure_cookie)
    return response
