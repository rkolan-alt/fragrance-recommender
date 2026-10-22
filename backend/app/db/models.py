"""Account tables; the perfume catalog remains in offline artifacts."""

import uuid
from datetime import UTC, datetime

from fastapi_users.db import SQLAlchemyBaseOAuthAccountTableUUID, SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class OAuthAccount(SQLAlchemyBaseOAuthAccountTableUUID, Base):
    pass


class User(SQLAlchemyBaseUserTableUUID, Base):
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    pass


class CollectionItem(Base):
    __tablename__ = "collection_items"
    __table_args__ = (
        UniqueConstraint("user_id", "perfume_id"),
        CheckConstraint("status IN ('owned', 'wishlist', 'disliked')"),
        CheckConstraint("personal_rating IS NULL OR personal_rating BETWEEN 1 AND 5"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    perfume_id: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), default="owned")
    personal_rating: Mapped[int | None]
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SavedFilter(Base):
    __tablename__ = "saved_filters"
    __table_args__ = (UniqueConstraint("user_id", "name"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    filter_json: Mapped[dict] = mapped_column(JSON)
    is_default: Mapped[bool] = mapped_column(default=False)
    is_custom_row: Mapped[bool] = mapped_column(default=False)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "perfume_id", "action"),
        CheckConstraint("action IN ('not_interested', 'clicked', 'bought')"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    perfume_id: Mapped[int]
    action: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
