from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    serpapi_key: str = ""
    pricing_daily_request_limit: int = 10
    pricing_lazy_per_request: int = 2
    pricing_cache_days: int = 7
    pricing_auto_refresh: bool = False
    auth_secret: str = "change-me"
    cookie_secure: bool = False
    session_lifetime_seconds: int = 604800
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_url: str = "http://localhost:8001/auth/google/callback"
    email_backend: str = "outbox"
    resend_api_key: str = ""
    email_from: str = "Fragrance Recommender <onboarding@resend.dev>"
    mail_outbox: Path = REPO_ROOT / "backend" / "mail-outbox"
    rate_limit_storage_uri: str = "memory://"
    frontend_origin: str = "http://localhost:3000"
    data_dir: Path = REPO_ROOT / "data"
    environment: Literal["development", "test", "production"] = "development"

    @model_validator(mode="after")
    def production_settings(self):
        if self.environment != "production":
            return self
        issues = []
        origin = urlsplit(self.frontend_origin)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
        ):
            issues.append("FRONTEND_ORIGIN must be a plain HTTPS origin")
        if not self.cookie_secure:
            issues.append("COOKIE_SECURE must be true")
        if self.auth_secret == "change-me" or len(self.auth_secret) < 32:
            issues.append("AUTH_SECRET must contain at least 32 characters")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            issues.append("DATABASE_URL must use PostgreSQL with asyncpg")
        if self.email_backend != "resend" or not self.resend_api_key:
            issues.append("Configure Resend email delivery before production")
        if "onboarding@resend.dev" in self.email_from:
            issues.append("EMAIL_FROM must use your verified sending domain")
        if bool(self.google_oauth_client_id) != bool(self.google_oauth_client_secret):
            issues.append("Configure both Google OAuth credentials or neither")
        if self.google_oauth_client_id:
            expected = self.frontend_origin.rstrip("/") + "/api/account/auth/google/callback"
            if self.google_oauth_redirect_url != expected:
                issues.append(
                    "GOOGLE_OAUTH_REDIRECT_URL must use the website callback: "
                    "/api/account/auth/google/callback"
                )
        if issues:
            raise ValueError("; ".join(issues))
        self.frontend_origin = self.frontend_origin.rstrip("/")
        return self


settings = Settings()
