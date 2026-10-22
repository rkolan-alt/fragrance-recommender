from fastapi import Depends
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import OAuthAccount, User

engine = create_async_engine(settings.database_url)
if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def sqlite_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with session_factory() as session:
        yield session


async def get_user_db(session=Depends(get_session)):  # noqa: B008
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)
