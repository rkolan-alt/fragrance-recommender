import asyncio
import io
import tarfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.mail import MailDeliveryError, send_account_email
from app.config import Settings, settings
from app.observability import RequestDiagnostics
from pipeline.artifacts import FILES, bundle, verify


def test_production_settings_require_real_services_and_hide_secret_values():
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, environment="production", auth_secret="private-test-secret")
    assert "COOKIE_SECURE" in str(caught.value)
    assert "private-test-secret" not in str(caught.value)
    valid = dict(
        environment="production",
        cookie_secure=True,
        auth_secret="x" * 48,
        database_url="postgresql+asyncpg://example:example@localhost/fragrance",
        frontend_origin="https://fragrance.example",
        email_backend="resend",
        resend_api_key="test-key",
        email_from="Fragrance <hello@fragrance.example>",
        google_oauth_client_id="",
        google_oauth_client_secret="",
    )
    assert Settings(_env_file=None, **valid).environment == "production"
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            **{
                **valid,
                "google_oauth_client_id": "id",
                "google_oauth_client_secret": "test-secret",
                "google_oauth_redirect_url": "https://api.example/auth/google/callback",
            },
        )


def test_request_errors_are_generic_and_do_not_log_query_tokens(caplog):
    from app.observability import logger

    logger.addHandler(caplog.handler)
    app = FastAPI()
    app.add_middleware(RequestDiagnostics)

    @app.get("/failure")
    def fail():
        raise RuntimeError("private-exception-value")

    try:
        response = TestClient(app).get("/failure?token=private-query-token")
        assert response.status_code == 500
        assert response.json()["request_id"] == response.headers["X-Request-ID"]
        assert "private" not in response.text
        assert "private-query-token" not in caplog.text
        assert "private-exception-value" not in caplog.text
    finally:
        logger.removeHandler(caplog.handler)


def test_artifact_bundle_only_contains_catalog_files_and_detects_tampering(tmp_path, monkeypatch):
    import app.engine.catalog

    monkeypatch.setattr(
        app.engine.catalog, "load_catalog", lambda _: SimpleNamespace(perfumes=range(3))
    )
    source = tmp_path / "processed"
    source.mkdir()
    for name in FILES:
        (source / name).write_bytes(b"catalog data")
    (source / ".env").write_text("SECRET=do-not-package")
    (source / "accounts.db").write_bytes(b"do-not-package")
    output = tmp_path / "artifacts.tar.gz"
    bundle(source, output)
    assert verify(output)["catalog_rows"] == 3
    with tarfile.open(output) as original:
        assert all(not member.uname and not member.gname for member in original.getmembers())
        entries = {member.name: original.extractfile(member).read() for member in original}
    assert set(entries) == {*FILES, "manifest.json"}
    entries[FILES[0]] = b"corrupt"
    with tarfile.open(output, "w:gz") as archive:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="mismatch"):
        verify(output)


def test_resend_failure_is_sanitized_and_payload_uses_configured_sender(monkeypatch):
    monkeypatch.setattr(settings, "email_backend", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "private-api-key")
    monkeypatch.setattr(settings, "email_from", "Fragrance <hello@example.com>")
    calls = []

    async def post(self, url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(
            503, request=httpx.Request("POST", url), json={"message": "private-provider-value"}
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(MailDeliveryError) as caught:
        asyncio.run(send_account_email("test@example.com", "test-token", "verify-email"))
    assert "private" not in str(caught.value)
    assert calls[0]["json"]["from"] == "Fragrance <hello@example.com>"
    assert "verify-email?token=test-token" in calls[0]["json"]["text"]


def test_readiness_fails_safely_when_catalog_is_unavailable(monkeypatch):
    from app.api import routes
    from app.main import app

    def missing():
        raise OSError("private-file-path")

    monkeypatch.setattr(routes, "get_catalog", missing)
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert response.headers["cache-control"] == "no-store"


def test_google_only_production_requires_google_but_not_resend():
    config = dict(
        environment="production",
        email_password_enabled=False,
        cookie_secure=True,
        auth_secret="x" * 48,
        database_url="postgresql+asyncpg://example:example@localhost/fragrance",
        frontend_origin="https://fragrance-web.example.run.app",
        google_oauth_redirect_url="https://fragrance-web.example.run.app/api/account/auth/google/callback",
        google_oauth_client_id="test-id",
        google_oauth_client_secret="test-secret",
        email_backend="outbox",
        resend_api_key="",
    )
    assert Settings(_env_file=None, **config).email_password_enabled is False
    with pytest.raises(ValidationError, match="Configure Google"):
        Settings(
            _env_file=None,
            **{**config, "google_oauth_client_id": "", "google_oauth_client_secret": ""},
        )
    with pytest.raises(ValidationError, match="Resend"):
        Settings(_env_file=None, **{**config, "email_password_enabled": True})
