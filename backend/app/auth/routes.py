import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi_users.router.oauth import generate_state_token

from app.auth.google import GoogleOpenID
from app.auth.policy import require_email_password
from app.auth.users import (
    SECRET,
    UserCreate,
    UserRead,
    UserUpdate,
    backend,
    current_user,
    fastapi_users,
)
from app.config import settings

router = APIRouter()


@router.get("/auth/options")
def options():
    return {
        "google_enabled": bool(
            settings.google_oauth_client_id and settings.google_oauth_client_secret
        ),
        "frontend_origin": settings.frontend_origin,
        "email_password_enabled": settings.email_password_enabled,
    }


password_router = APIRouter(dependencies=[Depends(require_email_password)])
password_router.include_router(fastapi_users.get_register_router(UserRead, UserCreate))
password_router.include_router(fastapi_users.get_reset_password_router())
password_router.include_router(fastapi_users.get_verify_router(UserRead))
login_router = fastapi_users.get_auth_router(backend)
login_router.routes = [r for r in login_router.routes if r.path == "/login"]
password_router.include_router(login_router)
router.include_router(password_router, prefix="/auth")
logout_router = fastapi_users.get_auth_router(backend)
logout_router.routes = [r for r in logout_router.routes if r.path == "/logout"]
router.include_router(logout_router, prefix="/auth")
users_router = fastapi_users.get_users_router(UserRead, UserUpdate)
# Expose only self-service routes; no public admin/user-list surface.
users_router.routes = [r for r in users_router.routes if r.path == "/me" and "GET" in r.methods]
router.include_router(users_router, prefix="/users")


@router.get("/auth/csrf")
def csrf(response: Response):
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        "fragrance_csrf",
        token,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
        max_age=3600,
    )
    response.headers["Cache-Control"] = "no-store"
    return {"csrf_token": token}


def google_routes():
    router = APIRouter()
    client = GoogleOpenID(settings.google_oauth_client_id, settings.google_oauth_client_secret)

    async def check_oauth_state(request: Request):
        import hmac

        state = request.query_params.get("state", "")
        bound = request.cookies.get("fragrance_oauth_state", "")
        if not state or not bound or not hmac.compare_digest(state, bound):
            raise HTTPException(400, "OAuth browser state mismatch")

    login = fastapi_users.get_oauth_router(
        client,
        backend,
        SECRET,
        redirect_url=settings.google_oauth_redirect_url,
        associate_by_email=False,
        is_verified_by_default=True,
    )
    login.routes = [r for r in login.routes if r.path != "/authorize"]
    router.include_router(login, prefix="/auth/google", dependencies=[Depends(check_oauth_state)])

    association_redirect = settings.google_oauth_redirect_url.replace(
        "/auth/google/callback", "/auth/google/associate/callback"
    )
    associate = fastapi_users.get_oauth_associate_router(
        client, UserRead, SECRET, redirect_url=association_redirect, requires_verification=True
    )
    associate.routes = [r for r in associate.routes if r.path != "/authorize"]
    router.include_router(
        associate, prefix="/auth/google/associate", dependencies=[Depends(check_oauth_state)]
    )

    async def authorization(response, redirect, state_data):
        state = generate_state_token({**state_data, "nonce": secrets.token_urlsafe(32)}, SECRET)
        url = await client.get_authorization_url(redirect, state)
        response.set_cookie(
            "fragrance_oauth_state",
            state,
            max_age=600,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
        )
        response.headers["Cache-Control"] = "no-store"
        return {"authorization_url": url}

    @router.get("/auth/google/authorize")
    async def authorize(response: Response, web: bool = False):
        response.set_cookie(
            "fragrance_oauth_web",
            "1" if web else "0",
            max_age=600,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
        )
        return await authorization(response, settings.google_oauth_redirect_url, {})

    @router.get("/auth/google/associate/authorize")
    async def associate_authorize(
        response: Response,
        web: bool = False,
        user=Depends(current_user),  # noqa: B008
    ):  # noqa: B008
        if not user.is_verified:
            raise HTTPException(403, "Verify your email before connecting Google")
        response.set_cookie(
            "fragrance_oauth_web",
            "1" if web else "0",
            max_age=600,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
        )
        return await authorization(response, association_redirect, {"sub": str(user.id)})

    return router


if settings.google_oauth_client_id and settings.google_oauth_client_secret:
    router.include_router(google_routes())
