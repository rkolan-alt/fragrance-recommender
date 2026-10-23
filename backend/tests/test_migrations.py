import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url


def test_migration_upgrade_check_and_downgrade(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"}
    for command in (("upgrade", "head"), ("check",), ("downgrade", "base"), ("upgrade", "head")):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


@pytest.mark.skipif(
    not os.environ.get("TEST_POSTGRES_URL"), reason="Disposable PostgreSQL not configured"
)
def test_postgres_migrations():
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.db.models import Base

    url = os.environ["TEST_POSTGRES_URL"]
    assert make_url(url).database == "fragrance_test", (
        "Only use the disposable fragrance_test database"
    )

    async def clear_test_database():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await engine.dispose()

    asyncio.run(clear_test_database())
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": url}
    for command in (("upgrade", "head"), ("check",), ("downgrade", "base"), ("upgrade", "head")):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *command],
            cwd=backend,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
