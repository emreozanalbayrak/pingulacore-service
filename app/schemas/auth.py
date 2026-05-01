from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _validate_email(value: str) -> str:
    cleaned = value.strip().lower()
    if not _EMAIL_RE.match(cleaned):
        raise ValueError("Geçersiz e-posta adresi")
    return cleaned


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)
    display_name: str | None = None

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return _validate_email(value)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return _validate_email(value)


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str | None
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthTokenResponse(BaseModel):
    token: str
    expires_at: datetime | None
    user: UserResponse
