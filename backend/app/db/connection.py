"""Translate provider PostgreSQL URLs into asyncpg settings without exposing secrets."""

import ssl

from sqlalchemy.engine import make_url


def async_database_url(value: str) -> str:
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    return url.render_as_string(hide_password=False)


def connection_settings(value: str):
    url = make_url(async_database_url(value))
    options = {"pool_pre_ping": True}
    if url.drivername != "postgresql+asyncpg":
        return url, options
    query = dict(url.query)
    mode = query.pop("sslmode", query.pop("ssl", None))
    binding = query.pop("channel_binding", None)
    if binding not in {None, "require", "prefer", "disable"}:
        raise ValueError("Unsupported PostgreSQL channel binding setting")
    neon = bool(url.host and url.host.endswith(".neon.tech"))
    if neon or mode in {"require", "verify-ca", "verify-full"} or binding == "require":
        # asyncpg does not accept libpq's sslmode/channel_binding keywords.
        # Use certificate AND hostname verification, including for sslmode=require.
        options["connect_args"] = {"ssl": ssl.create_default_context()}
        if mode not in {None, "require", "verify-ca", "verify-full"}:
            raise ValueError("Neon connections require verified TLS")
    elif mode is not None or binding is not None:
        raise ValueError("Unsupported PostgreSQL TLS parameters; use verified TLS")
    url = url.set(query=query)
    options.update(pool_size=2, max_overflow=1)
    return url, options
