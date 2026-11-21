"""The web UI: one screen at "/" plus sign in and sign out. All data comes from the REST API under /api/v1."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.controllers.deps import TOKEN_COOKIE, CurrentUser, get_container, resolve_user
from app.core.security import create_access_token
from app.models import auth_service
from app.models.container import Container
from app.models.db import DbSession

VIEWS_DIR = Path(__file__).resolve().parents[2] / "views"
templates = Jinja2Templates(directory=str(VIEWS_DIR / "templates"))
router = APIRouter(include_in_schema=False)

DEMO_ACCOUNTS = [
    ("dr.evans", "Clinician", "rxd_seed_pw_clinician"),
    ("rph.aniket", "Pharmacist", "rxd_seed_pw_pharmacist"),
    ("admin.sanoj", "Admin", "rxd_seed_pw_admin"),
]


def _current_user(request: Request, db: DbSession, container: Container) -> CurrentUser | None:
    return resolve_user(request.cookies.get(TOKEN_COOKIE), db, container)


def _accounts(container: Container) -> list[dict]:
    """Demo accounts for the sign-in screen. Passwords are shown only outside production."""
    show = not container.settings.is_production
    return [
        {"username": u, "role": r, "password": getattr(container.settings, p) if show else ""}
        for u, r, p in DEMO_ACCOUNTS
    ]


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: DbSession, container: Annotated[Container, Depends(get_container)]):
    user = _current_user(request, db, container)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "app.html", {"user": user})


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, container: Annotated[Container, Depends(get_container)]):
    return templates.TemplateResponse(request, "login.html", {"accounts": _accounts(container), "error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    username: Annotated[str, Form(max_length=64)],
    password: Annotated[str, Form(max_length=200)],
):
    user = auth_service.authenticate(db, username.strip(), password)
    if user is None:
        return templates.TemplateResponse(
            request, "login.html",
            {"accounts": _accounts(container), "error": "That username and password do not match."},
            status_code=401,
        )
    token, expires_in = create_access_token(
        user.username, user.role,
        secret=container.settings.rxd_jwt_secret, ttl_minutes=container.settings.rxd_jwt_ttl_min,
    )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(TOKEN_COOKIE, token, max_age=expires_in, httponly=True, samesite="strict",
                        secure=container.settings.is_production, path="/")
    return response


@router.post("/logout")
def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(TOKEN_COOKIE, path="/")
    return response
