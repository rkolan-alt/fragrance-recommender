"""CSRF checks, OAuth state cleanup and bounded per-process auth throttling."""

import hashlib
import hmac
import json
from urllib.parse import parse_qs

from fastapi import Request
from limits import parse
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

from app.auth.users import SECRET, SESSION_COOKIE
from app.config import settings

throttle = MovingWindowRateLimiter(storage_from_string(settings.rate_limit_storage_uri))
AUTH_LIMIT = parse("10/minute")
AUTH_IP_LIMIT = parse("100/minute")


class AccountSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
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
        if (path.startswith("/auth/") or path == "/me/password") and request.method == "POST":
            address = request.client.host if request.client else "unknown"
            raw = await request.body()
            if len(raw) > 16_384:
                return JSONResponse(
                    {"detail": "Authentication request is too large"}, status_code=413
                )
            try:
                data = (
                    json.loads(raw)
                    if "application/json" in request.headers.get("content-type", "")
                    else {k: v[0] for k, v in parse_qs(raw.decode()).items()}
                )
                identity = (
                    data.get("email") or data.get("username") if isinstance(data, dict) else None
                )
            except (ValueError, UnicodeError):
                identity = None
            identity = (
                identity.strip().casefold()
                if isinstance(identity, str)
                else request.cookies.get(SESSION_COOKIE, address)
            )
            bucket = hmac.new(SECRET.encode(), identity.encode(), hashlib.sha256).hexdigest()
            # Next.js clients share an upstream IP. Limit each account identity
            # separately while retaining a coarser aggregate address limit.
            if not throttle.hit(AUTH_IP_LIMIT, "address", address) or not throttle.hit(
                AUTH_LIMIT, "identity", bucket
            ):
                return JSONResponse(
                    {"detail": "Too many authentication attempts"},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
        response = await call_next(request)
        if (
            path in {"/auth/google/callback", "/auth/google/associate/callback"}
            and request.cookies.get("fragrance_oauth_web") == "1"
            and response.status_code >= 400
        ):
            response = RedirectResponse(
                settings.frontend_origin
                + (
                    "/?auth_error=google_link"
                    if path == "/auth/google/associate/callback"
                    else "/?auth_error=google"
                ),
                status_code=303,
            )
        elif (
            path == "/auth/google/associate/callback"
            and request.cookies.get("fragrance_oauth_web") == "1"
            and response.status_code == 200
        ):
            response = RedirectResponse(
                settings.frontend_origin + "/?google_connected=1", status_code=303
            )
        if account or private_recommend:
            response.headers["Cache-Control"] = "no-store"
        if path in {"/auth/google/callback", "/auth/google/associate/callback"}:
            response.delete_cookie(
                "fragrance_oauth_web",
                secure=settings.cookie_secure,
                httponly=True,
                samesite="lax",
            )
            response.delete_cookie(
                "fragrance_oauth_state",
                secure=settings.cookie_secure,
                httponly=True,
                samesite="lax",
            )
        return response
