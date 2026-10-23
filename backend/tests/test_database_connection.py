import ssl

import pytest
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db.connection import connection_settings


def test_neon_urls_preserve_credentials_and_use_verified_tls():
    raw = "postgresql://user:p%40ss%25word@ep-example-pooler.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    config = Settings(_env_file=None, database_url=raw)
    assert config.database_url.startswith("postgresql+asyncpg://")
    url, options = connection_settings(config.database_url)
    assert url.password == "p@ss%word"
    assert "sslmode" not in url.query and "channel_binding" not in url.query
    tls = options["connect_args"]["ssl"]
    assert tls.verify_mode == ssl.CERT_REQUIRED and tls.check_hostname
    assert options["pool_size"] == 2 and options["max_overflow"] == 1


def test_unpooled_url_is_available_to_migrations_without_changing_app_url():
    config = Settings(
        _env_file=None,
        database_url="postgresql://u:p@ep-example-pooler.aws.neon.tech/neondb",
        database_url_unpooled="postgresql://u:p@ep-example.aws.neon.tech/neondb",
    )
    assert "-pooler" in make_url(config.database_url).host
    assert "-pooler" not in make_url(config.database_url_unpooled).host


def test_local_sqlite_and_postgres_need_no_neon_configuration():
    url, options = connection_settings("sqlite+aiosqlite:///./dev.db")
    assert url.drivername == "sqlite+aiosqlite"
    assert "pool_size" not in options and "connect_args" not in options
    _, options = connection_settings("postgresql+asyncpg://u:p@localhost/test")
    assert "connect_args" not in options


def test_neon_rejects_insecure_tls():
    with pytest.raises(ValueError, match="verified TLS"):
        connection_settings("postgresql://u:p@ep-example.aws.neon.tech/db?sslmode=disable")
