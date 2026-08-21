from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from fastapi.responses import JSONResponse, RedirectResponse

from veritas_runtime.auth.oauth import OAuthExchangeError
from veritas_runtime.auth.service import GoogleConnectionService, InvalidAuthorizationAttempt
from veritas_runtime.auth.storage import CredentialIntegrityError
from veritas_runtime.workspace.contracts import CAPABILITY_SCOPES, REQUIRED_WORKSPACE_SCOPES

LOCAL_COOKIE_NAME = "veritas_google_oauth"
PRODUCTION_COOKIE_NAME = "__Host-veritas_google_oauth"


def create_google_auth_router(
    service: GoogleConnectionService | None,
    *,
    secure_cookie: bool,
) -> APIRouter:
    router = APIRouter()
    cookie_name = PRODUCTION_COOKIE_NAME if secure_cookie else LOCAL_COOKIE_NAME

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
        response.headers["Cache-Control"] = "no-store"
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
