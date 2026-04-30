from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import User
from app.schemas.auth import (
    AuthTokenResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _to_token_response(user: User, raw_token: str, expires_at) -> AuthTokenResponse:
    return AuthTokenResponse(
        token=raw_token,
        expires_at=expires_at,
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    user_agent: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    settings = get_settings()
    if not settings.signup_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kayıt şu an kapalı")

    if len(payload.password) < settings.password_min_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Şifre en az {settings.password_min_length} karakter olmalı",
        )

    if auth_service.get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu e-posta ile bir hesap zaten var",
        )

    user = auth_service.create_user(
        db,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        is_admin=False,
    )
    token = auth_service.create_token(db, user, user_agent=user_agent)
    db.commit()
    db.refresh(user)
    return _to_token_response(user, token.token, token.expires_at)


@router.post("/login", response_model=AuthTokenResponse)
def login(
    payload: LoginRequest,
    user_agent: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    user = auth_service.get_user_by_email(db, payload.email)
    if user is None or not user.is_active or not auth_service.verify_password(
        payload.password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-posta veya şifre hatalı",
        )

    token = auth_service.create_token(db, user, user_agent=user_agent)
    db.commit()
    return _to_token_response(user, token.token, token.expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    authorization: str | None = Header(default=None),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            auth_service.revoke_token(db, parts[1].strip())
    return None


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)
