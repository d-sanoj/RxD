"""Shared controller dependencies: the container, the current user and role checks."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import TokenError, decode_access_token
from app.models.auth_service import get_active_user
from app.models.container import Container
from app.models.db import DbSession

TOKEN_COOKIE = "rxd_token"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: str


def get_container(request: Request) -> Container:
    return request.app.state.container


def resolve_user(raw_token: str | None, db: DbSession, container: Container) -> CurrentUser | None:
    """Return the signed-in user, or None. The role is read from the database, not the token."""
    if not raw_token:
        return None
    try:
        payload = decode_access_token(raw_token, secret=container.settings.rxd_jwt_secret)
    except TokenError:
        return None
    user = get_active_user(db, payload["sub"])
    return CurrentUser(username=user.username, role=user.role) if user else None


def current_user(
    request: Request,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    bearer: Annotated[str | None, Depends(oauth2_scheme)],
) -> CurrentUser:
    user = resolve_user(bearer or request.cookies.get(TOKEN_COOKIE), db, container)
    if user is None:
        raise UnauthorizedError("Sign in to continue.", code="not_authenticated")
    return user


def require_roles(*roles: str):
    def checker(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if user.role not in roles:
            raise ForbiddenError(
                f"Your role ({user.role}) cannot do this.", code="forbidden", details={"required_roles": list(roles)}
            )
        return user

    return checker
