from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from httpx_oauth.exceptions import GetIdEmailError

from app.api.accounts import router as accounts_router
from app.api.routes import router
from app.auth.routes import router as auth_router
from app.auth.security import AccountSecurityMiddleware
from app.config import settings

app = FastAPI(title="Fragrance Recommender API")
app.add_middleware(AccountSecurityMiddleware)

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


app.include_router(router)

app.include_router(auth_router)
app.include_router(accounts_router)


# Provider failures should be actionable responses rather than unhandled 500s.


@app.exception_handler(GetIdEmailError)
async def google_identity_error(request, exc):
    return JSONResponse(
        {"detail": "Google could not provide a verified email. Start a new sign-in attempt."},
        status_code=502,
        headers={"Cache-Control": "no-store"},
    )
