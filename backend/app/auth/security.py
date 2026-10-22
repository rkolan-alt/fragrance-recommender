"""CSRF checks, OAuth state cleanup and bounded per-process auth throttling."""

import hmac

from fastapi import Request
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.auth.users import SESSION_COOKIE
from app.config import settings

throttle = MovingWindowRateLimiter(storage_from_string(settings.rate_limit_storage_uri))
AUTH_LIMIT = parse("10/minute")


class AccountSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/auth/") and request.method == "POST":
            address = request.client.host if request.client else "unknown"
            if not throttle.hit(AUTH_LIMIT, address):
                return JSONResponse(
                    {"detail": "Too many authentication attempts"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
        account = path.startswith(("/auth/", "/me", "/users/"))
        private_recommend = path == "/recommend" and SESSION_COOKIE in request.cookies
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and (account or private_recommend):
            cookie = request.cookies.get("fragrance_csrf", "")
            header = request.headers.get("X-CSRF-Token", "")
            origin = request.headers.get("origin")
            if (
                not cookie
                or not header
                or not hmac.compare_digest(cookie, header)
                or (origin is not None and origin != settings.frontend_origin)
            ):
                return JSONResponse({"detail": "Invalid CSRF token or origin"}, status_code=403)
        response = await call_next(request)
        if account or private_recommend:
            response.headers["Cache-Control"] = "no-store"
        if path in {"/auth/google/callback", "/auth/google/associate/callback"}:
            response.delete_cookie(
                "fragrance_oauth_state",
                secure=settings.cookie_secure,
                httponly=True,
                samesite="lax",
            )
        return response
