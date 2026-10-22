from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    serpapi_key: str = ""
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


settings = Settings()
