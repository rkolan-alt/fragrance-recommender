from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    serpapi_key: str = ""
    auth_secret: str = "change-me"
    frontend_origin: str = "http://localhost:3000"
    data_dir: Path = REPO_ROOT / "data"


settings = Settings()
