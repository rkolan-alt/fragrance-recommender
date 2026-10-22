import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx_oauth.exceptions import GetIdEmailError

from app.auth.google import USERINFO_ENDPOINT, GoogleOpenID
from app.main import google_identity_error


def test_userinfo_uses_bearer_token_and_verified_stable_subject(monkeypatch):
    google = GoogleOpenID("client", "secret")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, json={"sub": "stable-id", "email": "user@example.com", "email_verified": True}
        )

    monkeypatch.setattr(
        google,
        "get_httpx_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert asyncio.run(google.get_id_email("test-access-token")) == (
        "stable-id",
        "user@example.com",
    )
    assert str(requests[0].url) == USERINFO_ENDPOINT
    assert requests[0].headers["Authorization"] == "Bearer test-access-token"
    assert not requests[0].url.query
    assert google.base_scopes == ["openid", "email", "profile"]


@pytest.mark.parametrize(
    "status, payload",
    [
        (403, {"error": "denied"}),
        (401, {"error": "invalid_token"}),
        (200, {"sub": "id", "email": "user@example.com", "email_verified": False}),
        (200, {"sub": "id", "email": "user@example.com", "email_verified": "true"}),
        (200, {"email": "user@example.com", "email_verified": True}),
        (200, {"sub": "id", "email_verified": True}),
        (200, []),
    ],
)
def test_bad_profile_cannot_create_verified_account(monkeypatch, status, payload):
    google = GoogleOpenID("client", "secret")
    monkeypatch.setattr(
        google,
        "get_httpx_client",
        lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload))
        ),
    )
    with pytest.raises(GetIdEmailError):
        asyncio.run(google.get_id_email("test-access-token"))


def test_identity_failure_is_safe_actionable_response():
    app = FastAPI()
    app.add_exception_handler(GetIdEmailError, google_identity_error)

    @app.get("/callback")
    async def callback():
        raise GetIdEmailError(response=httpx.Response(403, json={"sensitive": "not-for-client"}))

    response = TestClient(app).get("/callback")
    assert response.status_code == 502
    assert "new sign-in" in response.json()["detail"]
    assert "sensitive" not in response.text
