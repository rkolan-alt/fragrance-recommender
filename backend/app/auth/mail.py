"""Explicit development outbox, or configured Resend delivery."""

import json
import uuid
from urllib.parse import urlencode

import httpx

from app.config import settings


class MailDeliveryError(Exception):
    """Safe failure; provider responses may contain private recipient details."""


async def send_account_email(email: str, token: str, purpose: str):
    link = f"{settings.frontend_origin}/{purpose}?{urlencode({'token': token})}"
    message = {"to": email, "subject": f"Fragrance Recommender: {purpose}", "text": link}
    if settings.email_backend == "outbox":
        if settings.cookie_secure:
            raise RuntimeError("Configure real email delivery in production")
        settings.mail_outbox.mkdir(parents=True, exist_ok=True)
        path = settings.mail_outbox / f"{uuid.uuid4()}.json"
        path.write_text(json.dumps(message))
        path.chmod(0o600)
    elif settings.email_backend == "resend" and settings.resend_api_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json={"from": settings.email_from, **message},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MailDeliveryError("Email delivery is temporarily unavailable") from exc
    else:
        raise MailDeliveryError("Email backend is not configured")
