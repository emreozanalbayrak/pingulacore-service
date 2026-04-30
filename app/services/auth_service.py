from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AuthToken, User, utcnow

_SCRYPT_N = 16384
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64
_LAST_USED_REFRESH = timedelta(minutes=5)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def hash_password(plain: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        plain.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(plain: str, stored: str) -> bool:
    try:
        algo, n_str, r_str, p_str, salt_b64, hash_b64 = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    try:
        n, r, p = int(n_str), int(r_str), int(p_str)
        salt = _b64decode(salt_b64)
        expected = _b64decode(hash_b64)
    except (ValueError, base64.binascii.Error):
        return False
    candidate = hashlib.scrypt(
        plain.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
    )
    return hmac.compare_digest(candidate, expected)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    stmt = select(User).where(User.email == normalize_email(email))
    return db.execute(stmt).scalar_one_or_none()


def create_user(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
    is_admin: bool = False,
) -> User:
    user = User(
        email=normalize_email(email),
        password_hash=hash_password(password),
        display_name=(display_name.strip() if display_name else None) or None,
        is_admin=is_admin,
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def create_token(db: Session, user: User, *, user_agent: str | None = None) -> AuthToken:
    settings = get_settings()
    ttl_hours = settings.auth_token_ttl_hours
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        if ttl_hours > 0
        else None
    )
    token = AuthToken(
        token=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=expires_at,
        user_agent=user_agent[:512] if user_agent else None,
    )
    db.add(token)
    db.flush()
    return token


def lookup_token(db: Session, raw_token: str) -> tuple[User, AuthToken] | None:
    if not raw_token:
        return None
    record = db.get(AuthToken, raw_token)
    if record is None:
        return None
    if record.expires_at is not None:
        expires = record.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            db.delete(record)
            db.commit()
            return None
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        return None

    last_used = record.last_used_at
    if last_used is not None and last_used.tzinfo is None:
        last_used = last_used.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if last_used is None or (now - last_used) > _LAST_USED_REFRESH:
        record.last_used_at = now
        db.commit()
    return user, record


def revoke_token(db: Session, raw_token: str) -> None:
    record = db.get(AuthToken, raw_token)
    if record is not None:
        db.delete(record)
        db.commit()


def seed_admin_if_needed() -> None:
    from app.db.database import SessionLocal

    settings = get_settings()
    email = settings.admin_seed_email
    password = settings.admin_seed_password
    if not email or not password:
        return

    with SessionLocal() as db:
        existing = get_user_by_email(db, email)
        if existing is not None:
            return
        create_user(
            db,
            email=email,
            password=password,
            display_name="Admin",
            is_admin=True,
        )
        db.commit()
