"""Host-only browser cookies; explicit origin checks for cookie-authenticated writes."""

from fastapi import Request, Response
from starlette.responses import JSONResponse

from hrms.core.config import settings

TENANT_COOKIE = "hrms_session"
PLATFORM_COOKIE = "hrms_platform_session"
BROWSER_HEADER = "x-hrms-session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def cookie_name(*, platform: bool = False) -> str:
    name = PLATFORM_COOKIE if platform else TENANT_COOKIE
    return "__Host-" + name if settings.is_deployed else name


def token_from_request(request: Request, *, platform: bool = False) -> str:
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return request.cookies.get(cookie_name(platform=platform), "")


def issue_browser_session(
    request: Request, response: Response, token: str, seconds: int, *, platform: bool = False
) -> str:
    if request.headers.get(BROWSER_HEADER) != "cookie":
        return token  # Explicit API clients can still obtain bearer credentials.
    response.set_cookie(
        cookie_name(platform=platform),
        token,
        max_age=seconds,
        httponly=True,
        secure=settings.is_deployed,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return ""  # Browser credentials never appear in the JSON body.


def clear_browser_session(response: Response, *, platform: bool = False) -> None:
    response.delete_cookie(
        cookie_name(platform=platform),
        path="/",
        secure=settings.is_deployed,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


class BrowserSessionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        browser = request.headers.get(BROWSER_HEADER) == "cookie"
        cookie_auth = bool(
            request.cookies.get(cookie_name()) or request.cookies.get(cookie_name(platform=True))
        ) and not request.headers.get("authorization")
        if request.method not in SAFE_METHODS and (browser or cookie_auth):
            origin = request.headers.get("origin", "")
            if not browser or origin not in settings.cors_origins_list:
                response = JSONResponse(
                    {"detail": "Untrusted browser request origin"}, status_code=403
                )
                return await response(scope, receive, send)
        await self.app(scope, receive, send)
