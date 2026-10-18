from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User
from app.security import create_access_token, hash_password, verify_password
from app.user_auth import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or "." not in normalized.split("@")[-1]:
            raise ValueError("Invalid email address")
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return value.strip().lower()


class UserRead(BaseModel):
    id: int
    email: str
    display_name: str
    role: str
    github_connected: bool
    github_login: str | None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


def _user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role or "user",
        github_connected=bool(user.github_token_sealed),
        github_login=user.github_login,
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    request: RegisterRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AuthResponse:
    email = request.email.strip().lower()
    existing = db.scalars(select(User).where(User.email == email)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        email=email,
        display_name=request.display_name.strip(),
        password_hash=hash_password(request.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(user_id=user.id, email=user.email, settings=settings)
    return AuthResponse(access_token=token, user=_user_read(user))


@router.post("/login", response_model=AuthResponse)
def login(
    request: LoginRequest, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AuthResponse:
    email = request.email.strip().lower()
    user = db.scalars(select(User).where(User.email == email)).first()
    if user is None or not verify_password(request.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user_id=user.id, email=user.email, settings=settings)
    return AuthResponse(access_token=token, user=_user_read(user))


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> UserRead:
    return _user_read(user)
