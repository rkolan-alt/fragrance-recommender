import logging
import secrets
import uuid

from fastapi import Depends, HTTPException
from fastapi_users import (
    BaseUserManager,
    FastAPIUsers,
    InvalidPasswordException,
    UUIDIDMixin,
    schemas,
)
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.auth.mail import MailDeliveryError, send_account_email
from app.config import settings
from app.db.models import AccessToken, User
from app.db.session import get_session, get_user_db

# Development works without a checked-in secret. Production must set a stable secret.
if settings.cookie_secure and (
    settings.auth_secret == "change-me" or len(settings.auth_secret) < 32
):
    raise RuntimeError("Set AUTH_SECRET to at least 32 random characters in production")
SECRET = settings.auth_secret if settings.auth_secret != "change-me" else secrets.token_urlsafe(48)
SESSION_COOKIE = "fragrance_session"


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def validate_password(self, password, user):
        if len(password) < 12 or len(password) > 128:
            raise InvalidPasswordException(reason="Use a password between 12 and 128 characters")

    async def on_after_register(self, user, request=None):
        if not user.is_verified:
            try:
                await self.request_verify(user, request)
            except MailDeliveryError:
                # The account is already committed. Return a usable signup;
                # verification can be requested again after the provider recovers.
                logging.getLogger("fragrance.requests").warning(
                    '{"event":"registration_email_failed"}'
                )

    async def on_after_request_verify(self, user, token, request=None):
        await send_account_email(user.email, token, "verify-email")

    async def on_after_forgot_password(self, user, token, request=None):
        await send_account_email(user.email, token, "reset-password")

    async def revoke_sessions(self, user):
        await self.user_db.session.execute(
            delete(AccessToken).where(AccessToken.user_id == user.id)
        )
        await self.user_db.session.commit()

    async def on_after_reset_password(self, user, request=None):
        await self.revoke_sessions(user)

    async def on_after_login(self, user, request=None, response=None):
        if (
            request is not None
            and response is not None
            and request.url.path == "/auth/google/callback"
            and request.cookies.get("fragrance_oauth_web") == "1"
        ):
            response.status_code = 303
            response.headers["Location"] = settings.frontend_origin + "/?signed_in=1"

    async def on_after_update(self, user, update_dict, request=None):
        if "password" in update_dict or "email" in update_dict:
            await self.revoke_sessions(user)

    async def oauth_associate_callback(
        self,
        user,
        oauth_name,
        access_token,
        account_id,
        account_email,
        expires_at=None,
        refresh_token=None,
        request=None,
    ):
        existing = await self.user_db.get_by_oauth_account(oauth_name, account_id)
        if existing is not None:
            if existing.id != user.id:
                raise HTTPException(
                    409, "This Google account is already connected to another account"
                )
            return user
        try:
            return await super().oauth_associate_callback(
                user,
                oauth_name,
                access_token,
                account_id,
                account_email,
                expires_at,
                refresh_token,
                request,
            )
        except IntegrityError as exc:
            await self.user_db.session.rollback()
            raise HTTPException(409, "This Google account is already connected") from exc


async def get_user_manager(user_db=Depends(get_user_db)):  # noqa: B008
    yield UserManager(user_db)


async def get_strategy(session=Depends(get_session)):  # noqa: B008
    return DatabaseStrategy(
        SQLAlchemyAccessTokenDatabase(session, AccessToken),
        lifetime_seconds=settings.session_lifetime_seconds,
    )


transport = CookieTransport(
    cookie_name=SESSION_COOKIE,
    cookie_max_age=settings.session_lifetime_seconds,
    cookie_secure=settings.cookie_secure,
    cookie_httponly=True,
    cookie_samesite="lax",
)
backend = AuthenticationBackend(name="cookie", transport=transport, get_strategy=get_strategy)
fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [backend])
current_user = fastapi_users.current_user(active=True)
optional_user = fastapi_users.current_user(optional=True, active=True)
