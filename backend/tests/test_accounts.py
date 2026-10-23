import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api import routes
from app.auth.security import throttle
from app.auth.users import SESSION_COOKIE
from app.config import settings
from app.db.models import AccessToken, Base, CollectionItem, Feedback, SavedFilter, User
from app.db.session import get_session
from app.main import app
from tests.test_engine import make_catalog, perfume

PASSWORD = "a-long-test-password"


@pytest.fixture
def account_app(tmp_path, monkeypatch):
    postgres = os.environ.get("TEST_POSTGRES_URL")
    if postgres and make_url(postgres).database != "fragrance_test":
        raise RuntimeError("PostgreSQL tests require the disposable fragrance_test database")
    engine = create_async_engine(
        postgres or f"sqlite+aiosqlite:///{tmp_path / 'accounts.db'}", poolclass=NullPool
    )
    if not postgres:

        @event.listens_for(engine.sync_engine, "connect")
        def fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def init():
        async with engine.begin() as conn:
            if postgres:
                await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(init())

    async def session_override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    monkeypatch.setattr(settings, "mail_outbox", tmp_path / "mail")
    monkeypatch.setattr(settings, "email_backend", "outbox")
    catalog = make_catalog(*(perfume(i) for i in range(1, 12)))
    monkeypatch.setattr(routes, "get_catalog", lambda: catalog)
    monkeypatch.setattr(routes, "get_details", lambda: catalog.perfumes)
    routes.cached_account_recommend.cache_clear()
    throttle.storage.reset()
    yield app, factory
    app.dependency_overrides.clear()
    routes.cached_account_recommend.cache_clear()
    asyncio.run(engine.dispose())


def client(app):
    c = TestClient(app)
    token = c.get("/auth/csrf").json()["csrf_token"]
    c.headers["X-CSRF-Token"] = token
    return c


def register(c, email="first@example.com"):
    r = c.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


def login(c, email="first@example.com", password=PASSWORD):
    r = c.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 204, r.text
    return r


def seed(c):
    response = c.post(
        "/me/collection/import", json={"items": [{"perfume_id": i} for i in range(1, 6)]}
    )
    assert response.status_code == 200, response.text


def mail(purpose):
    messages = [json.loads(p.read_text()) for p in settings.mail_outbox.glob("*.json")]
    return next(m for m in messages if purpose in m["subject"])


def token_from(message):
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(message["text"]).query)["token"][0]


def test_register_logout_login_persists_and_revokes_session(account_app):
    app, _ = account_app
    c = client(app)
    register(c)
    login(c)
    old_session = c.cookies.get(SESSION_COOKIE)
    seed(c)
    assert len(c.get("/me/collection").json()) == 5
    assert c.post("/auth/logout").status_code == 204
    assert c.get("/me/collection").status_code == 401
    c.cookies.set(SESSION_COOKIE, old_session)
    assert c.get("/me/collection").status_code == 401
    c.cookies.clear()
    c = client(app)
    login(c)
    assert len(c.get("/me/collection").json()) == 5
    r = c.post("/recommend", json={"categories": ["for_you"]})
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0]["items"]


def test_accounts_are_isolated_and_cannot_supply_owner(account_app):
    app, _ = account_app
    a, b = client(app), client(app)
    register(a)
    login(a)
    seed(a)
    saved = a.post("/me/filters", json={"name": "Fresh", "filter_json": {}}).json()
    register(b, "second@example.com")
    login(b, "second@example.com")
    assert b.get("/me/collection").json() == []
    assert b.get("/me/filters").json() == []
    assert b.patch("/me/collection/1", json={"status": "disliked"}).status_code == 404
    assert b.delete(f"/me/filters/{saved['id']}").status_code == 404
    assert b.post("/me/collection", json={"perfume_id": 7, "user_id": "forged"}).status_code == 422
    assert len(a.get("/me/collection").json()) == 5


def test_csrf_and_cookie_attributes(account_app):
    app, _ = account_app
    c = TestClient(app)
    assert c.post("/auth/register", json={}).status_code == 403
    c = client(app)
    register(c)
    r = login(c)
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=lax" in r.headers["set-cookie"]
    assert (
        c.post(
            "/me/collection", json={"perfume_id": 1}, headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/me/collection", json={"perfume_id": 1}, headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )


def test_import_is_atomic_and_preserves_existing(account_app):
    app, _ = account_app
    c = client(app)
    register(c)
    login(c)
    c.post("/me/collection", json={"perfume_id": 1, "personal_rating": 5})
    seed(c)
    seed(c)
    items = c.get("/me/collection").json()
    assert len(items) == 5
    assert next(i for i in items if i["perfume_id"] == 1)["personal_rating"] == 5
    r = c.post("/me/collection/import", json={"items": [{"perfume_id": 6}, {"perfume_id": -1}]})
    assert r.status_code == 422
    assert len(c.get("/me/collection").json()) == 5
    assert c.post("/me/collection", json={"perfume_id": 1}).status_code == 409


def test_saved_filters_feedback_and_collection_refresh(account_app):
    app, _ = account_app
    c = client(app)
    register(c)
    login(c)
    seed(c)
    r = c.post("/recommend", json={"categories": ["for_you"]})
    first = r.json()["rows"][0]["items"][0]["id"]
    c.post("/me/feedback", json={"perfume_id": first, "action": "not_interested"})
    r = c.post("/recommend", json={"categories": ["for_you"]})
    assert first not in {i["id"] for i in r.json()["rows"][0]["items"]}
    c.post("/me/collection", json={"perfume_id": 7, "status": "wishlist"})
    r = c.post("/recommend", json={"categories": ["for_you"]})
    assert 7 not in {i["id"] for i in r.json()["rows"][0]["items"]}
    saved = c.post(
        "/me/filters",
        json={
            "name": "Strict",
            "filter_json": {"min_votes": 1000000},
            "is_default": True,
            "is_custom_row": True,
        },
    )
    assert saved.status_code == 201, saved.text
    r = c.post("/recommend", json={})
    assert all(not row["items"] for row in r.json()["rows"])
    c.delete(f"/me/filters/{saved.json()['id']}")
    assert c.post("/recommend", json={}).json()["rows"][0]["items"]
    c.patch("/me/collection/1", json={"status": "wishlist"})
    assert c.post("/recommend", json={}).status_code == 422


def test_verification_and_password_reset_revoke_sessions(account_app):
    app, _ = account_app
    c = client(app)
    register(c)
    login(c)
    verify = token_from(mail("verify-email"))
    assert c.post("/auth/verify", json={"token": verify}).status_code == 200
    assert c.get("/users/me").json()["is_verified"]
    assert c.post("/auth/forgot-password", json={"email": "first@example.com"}).status_code == 202
    reset = token_from(mail("reset-password"))
    assert (
        c.post(
            "/auth/reset-password", json={"token": reset, "password": "a-new-long-password"}
        ).status_code
        == 200
    )
    assert c.get("/users/me").status_code == 401
    login(c, password="a-new-long-password")
    assert (
        c.post(
            "/auth/reset-password", json={"token": reset, "password": "a-third-long-password"}
        ).status_code
        == 400
    )


def test_delete_account_cascades_all_private_data(account_app):
    app, factory = account_app
    c = client(app)
    register(c)
    login(c)
    seed(c)
    c.post("/me/feedback", json={"perfume_id": 6, "action": "clicked"})
    c.post("/me/filters", json={"name": "Test", "filter_json": {}})
    assert (
        c.request(
            "DELETE",
            "/me",
            json={"confirmation_email": "first@example.com", "confirmation_text": "DELETE"},
        ).status_code
        == 204
    )
    assert c.get("/me/collection").status_code == 401

    async def empty():
        async with factory() as session:
            for model in (User, AccessToken, CollectionItem, SavedFilter, Feedback):
                assert list(await session.scalars(select(model))) == []

    asyncio.run(empty())


def test_auth_rate_limit(account_app):
    app, _ = account_app
    c = client(app)
    for _ in range(10):
        c.post("/auth/login", data={"username": "nobody@example.com", "password": PASSWORD})
    assert (
        c.post(
            "/auth/login", data={"username": "nobody@example.com", "password": PASSWORD}
        ).status_code
        == 429
    )
    register(c, "different@example.com")
    login(c, "different@example.com")


def test_password_change_revokes_sessions_and_enforces_strength(account_app):
    app, _ = account_app
    c = client(app)
    assert (
        c.post(
            "/auth/register", json={"email": "weak@example.com", "password": "short"}
        ).status_code
        == 400
    )
    register(c)
    login(c)
    assert c.patch("/users/me", json={"password": "new-long-password"}).status_code == 405
    assert (
        c.post(
            "/me/password", json={"current_password": "wrong", "new_password": "new-long-password"}
        ).status_code
        == 400
    )
    assert c.get("/users/me").status_code == 200
    assert (
        c.post(
            "/me/password", json={"current_password": PASSWORD, "new_password": "short"}
        ).status_code
        == 422
    )
    r = c.post(
        "/me/password", json={"current_password": PASSWORD, "new_password": "new-long-password"}
    )
    assert r.status_code == 204, r.text
    assert c.get("/users/me").status_code == 401
    login(c, password="new-long-password")
    assert c.get("/me/oauth").json() == []


def test_account_deletion_requires_explicit_matching_confirmation(account_app):
    app, _ = account_app
    c = client(app)
    register(c)
    login(c)
    assert c.delete("/me").status_code == 422
    assert (
        c.request(
            "DELETE",
            "/me",
            json={"confirmation_email": "other@example.com", "confirmation_text": "DELETE"},
        ).status_code
        == 400
    )
    assert c.get("/users/me").status_code == 200
    assert (
        c.request(
            "DELETE",
            "/me",
            json={"confirmation_email": "first@example.com", "confirmation_text": "DELETE"},
        ).status_code
        == 204
    )
    assert c.get("/users/me").status_code == 401


def test_registration_remains_usable_when_verification_delivery_fails(account_app, monkeypatch):
    from app.auth import users
    from app.auth.mail import MailDeliveryError

    async def fail(*args):
        raise MailDeliveryError("provider unavailable")

    monkeypatch.setattr(users, "send_account_email", fail)
    app, _ = account_app
    c = client(app)
    register(c)
    login(c)
    assert not c.get("/users/me").json()["is_verified"]
    response = c.post("/auth/request-verify-token", json={"email": "first@example.com"})
    assert response.status_code == 503
    assert "provider unavailable" not in response.text


def test_google_login_binds_state_to_browser(account_app, monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from fastapi import FastAPI

    from app.auth.google import GoogleOpenID
    from app.auth.routes import google_routes
    from app.auth.routes import router as auth_router
    from app.auth.security import AccountSecurityMiddleware

    app, _ = account_app
    monkeypatch.setattr(settings, "google_oauth_client_id", "test-client")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "test-secret")

    async def token(*args, **kwargs):
        return {"access_token": "provider-token", "token_type": "Bearer"}

    async def identity(*args, **kwargs):
        return "google-id-1", "google-user@example.com"

    monkeypatch.setattr(GoogleOpenID, "get_access_token", token)
    monkeypatch.setattr(GoogleOpenID, "get_id_email", identity)
    oauth_app = FastAPI()
    oauth_app.include_router(auth_router)
    oauth_app.include_router(google_routes())
    oauth_app.dependency_overrides.update(app.dependency_overrides)
    oauth_app.add_middleware(AccountSecurityMiddleware)
    c = TestClient(oauth_app)
    authorize = c.get("/auth/google/authorize")
    state = parse_qs(urlparse(authorize.json()["authorization_url"]).query)["state"][0]
    assert (
        c.get("/auth/google/callback", params={"code": "code", "state": "wrong"}).status_code == 400
    )
    # Wrong callback consumes the state; initiate a new flow.
    authorize = c.get("/auth/google/authorize")
    state = parse_qs(urlparse(authorize.json()["authorization_url"]).query)["state"][0]
    other_browser = TestClient(oauth_app)
    assert (
        other_browser.get(
            "/auth/google/callback", params={"code": "code", "state": state}
        ).status_code
        == 400
    )
    response = c.get("/auth/google/callback", params={"code": "code", "state": state})
    assert response.status_code == 204, response.text
    assert c.cookies.get(SESSION_COOKIE)
    assert not c.cookies.get("fragrance_oauth_state")

    # Website sign-in retains the session cookie and returns to the fixed app origin.
    authorize = c.get("/auth/google/authorize?web=true")
    state = parse_qs(urlparse(authorize.json()["authorization_url"]).query)["state"][0]
    response = c.get(
        "/auth/google/callback", params={"code": "code", "state": state}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == settings.frontend_origin + "/?signed_in=1"
    assert c.cookies.get(SESSION_COOKIE)
    assert not c.cookies.get("fragrance_oauth_web")

    # Invalid website callbacks return a retryable app screen and consume state.
    c.get("/auth/google/authorize?web=true")
    failed = c.get(
        "/auth/google/callback", params={"code": "code", "state": "wrong"}, follow_redirects=False
    )
    assert failed.status_code == 303
    assert failed.headers["location"] == settings.frontend_origin + "/?auth_error=google"
    assert not c.cookies.get("fragrance_oauth_state")
    assert not c.cookies.get("fragrance_oauth_web")

    async def second_identity(*args, **kwargs):
        return "google-id-2", "linked@example.com"

    monkeypatch.setattr(GoogleOpenID, "get_id_email", second_identity)
    authorize = c.get("/auth/google/associate/authorize")
    assert authorize.status_code == 200
    state = parse_qs(urlparse(authorize.json()["authorization_url"]).query)["state"][0]
    associated = c.get("/auth/google/associate/callback", params={"code": "code", "state": state})
    assert associated.status_code == 200, associated.text
    assert associated.json()["email"] == "google-user@example.com"

    authorize = c.get("/auth/google/associate/authorize?web=true")
    state = parse_qs(urlparse(authorize.json()["authorization_url"]).query)["state"][0]
    linked = c.get(
        "/auth/google/associate/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )
    assert linked.status_code == 303
    assert linked.headers["location"] == settings.frontend_origin + "/?google_connected=1"
    assert not c.cookies.get("fragrance_oauth_state")

    other = client(oauth_app)
    register(other, "second@example.com")
    login(other, "second@example.com")
    assert other.get("/auth/google/associate/authorize").status_code == 403
    verification = token_from(mail("verify-email"))
    assert other.post("/auth/verify", json={"token": verification}).status_code == 200
    authorize = other.get("/auth/google/associate/authorize")
    state = parse_qs(urlparse(authorize.json()["authorization_url"]).query)["state"][0]
    conflict = other.get("/auth/google/associate/callback", params={"code": "code", "state": state})
    assert conflict.status_code == 409


def test_oauth_identity_uniqueness_is_enforced_in_database(account_app):
    from sqlalchemy.exc import IntegrityError

    from app.db.models import OAuthAccount

    app, factory = account_app
    c = client(app)
    first = register(c)
    second = register(c, "second@example.com")

    async def check():
        import uuid

        async with factory() as session:
            for user_id in (first["id"], second["id"]):
                item = OAuthAccount(
                    user_id=uuid.UUID(user_id),
                    oauth_name="google",
                    account_id="same-google-identity",
                    account_email="test@example.com",
                    access_token="test-only",
                )
                session.add(item)
                if user_id == first["id"]:
                    await session.commit()
                else:
                    with pytest.raises(IntegrityError):
                        await session.commit()
                    await session.rollback()

    asyncio.run(check())


def test_csrf_errors_keep_cors_headers(account_app):
    app, _ = account_app
    c = TestClient(app)
    response = c.post("/auth/register", json={}, headers={"Origin": settings.frontend_origin})
    assert response.status_code == 403
    assert response.headers["access-control-allow-origin"] == settings.frontend_origin


def test_collection_contains_catalog_metadata_and_preserves_account_edits(account_app):
    app, _ = account_app
    c = client(app)
    register(c)
    login(c)
    seed(c)
    c.patch("/me/collection/1", json={"status": "wishlist", "personal_rating": 4})
    seed(c)
    items = c.get("/me/collection").json()
    assert len(items) == 5
    saved = next(item for item in items if item["perfume_id"] == 1)
    assert saved["status"] == "wishlist"
    assert saved["personal_rating"] == 4
    assert saved["perfume"]["id"] == 1
    assert isinstance(saved["perfume"]["name"], str)
    assert isinstance(saved["perfume"]["brand"], str)
    assert "image_url" in saved["perfume"]


def test_public_auth_options_never_expose_credentials(account_app):
    app, _ = account_app
    response = TestClient(app).get("/auth/options")
    assert response.status_code == 200
    assert set(response.json()) == {"google_enabled", "frontend_origin"}


def test_custom_rows_obey_active_filters_and_saved_filters_survive_login(account_app):
    app, _ = account_app
    c = client(app)
    register(c)
    login(c)
    seed(c)
    saved = c.post(
        "/me/filters", json={"name": "My citrus row", "filter_json": {}, "is_custom_row": True}
    ).json()
    key = f"custom_{saved['id']}"
    response = c.post("/recommend", json={"categories": [key]})
    assert response.status_code == 200
    assert response.json()["rows"][0]["items"]
    # Active filters apply to custom rows too; saved filters cannot bypass them.
    strict = c.post("/recommend", json={"filters": {"min_votes": 1000000}, "categories": [key]})
    assert strict.json()["rows"][0]["items"] == []
    c.post("/auth/logout")
    login(c)
    assert c.get("/me/filters").json()[0]["id"] == saved["id"]
    assert c.delete(f"/me/filters/{saved['id']}").status_code == 204
    assert c.get("/me/filters").json() == []
