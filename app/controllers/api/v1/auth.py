"""POST /api/v1/auth/token and GET /api/v1/auth/me."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.controllers.deps import CurrentUser, current_user, get_container
from app.core.errors import UnauthorizedError
from app.core.security import create_access_token
from app.models import auth_service
from app.models.container import Container
from app.models.db import DbSession
from app.views.schemas.auth import Me, Token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=Token, summary="Sign in with username and password")
def issue_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
) -> Token:
    user = auth_service.authenticate(db, form.username, form.password)
    if user is None:
        raise UnauthorizedError("Incorrect username or password.", code="invalid_credentials")
    token, expires_in = create_access_token(
        user.username, user.role,
        secret=container.settings.rxd_jwt_secret,
        ttl_minutes=container.settings.rxd_jwt_ttl_min,
    )
    return Token(access_token=token, token_type="bearer", expires_in=expires_in)


@router.get("/me", response_model=Me, summary="Who am I")
def who_am_i(user: Annotated[CurrentUser, Depends(current_user)]) -> Me:
    return Me(username=user.username, role=user.role)
