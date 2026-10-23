from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from httpx_oauth.exceptions import GetIdEmailError

from app.api.accounts import router as accounts_router
from app.api.routes import router
from app.auth.mail import MailDeliveryError
from app.auth.routes import router as auth_router
from app.auth.security import AccountSecurityMiddleware
from app.config import settings
from app.observability import RequestDiagnostics

app = FastAPI(title="Fragrance Recommender API")
app.add_middleware(AccountSecurityMiddleware)
app.add_middleware(RequestDiagnostics)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready():
    from sqlalchemy import select
    from starlette.concurrency import run_in_threadpool

    from app.api.routes import get_catalog
    from app.db.models import User
    from app.db.session import session_factory

    try:
        await run_in_threadpool(get_catalog)
        async with session_factory() as session:
            await session.execute(select(User.id).limit(1))
    except Exception:
        return JSONResponse(
            {"status": "not_ready"}, status_code=503, headers={"Cache-Control": "no-store"}
        )
    return {"status": "ready"}


app.include_router(router)

app.include_router(auth_router)
app.include_router(accounts_router)


@app.exception_handler(MailDeliveryError)
async def email_delivery_error(request, exc):
    return JSONResponse(
        {"detail": "Email delivery is temporarily unavailable. Please try again later."},
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )


# Provider failures should be actionable responses rather than unhandled 500s.


@app.exception_handler(GetIdEmailError)
async def google_identity_error(request, exc):
    return JSONResponse(
        {"detail": "Google could not provide a verified email. Start a new sign-in attempt."},
        status_code=502,
        headers={"Cache-Control": "no-store"},
    )
