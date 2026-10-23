"""Feature policy shared by password and email endpoints."""

from fastapi import HTTPException

from app.config import settings


def require_email_password():
    if not settings.email_password_enabled:
        raise HTTPException(404, "Email/password accounts are unavailable. Use Google sign-in.")
