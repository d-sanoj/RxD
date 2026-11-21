"""Application factory. create_app() wires settings, middleware, routers, static files and error handlers.

Run with:  uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.controllers.api.health import router as health_router
from app.controllers.api.v1 import api_v1_router
from app.controllers.web.pages import router as web_router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, log_event
from app.core.middleware import request_context
from app.models.container import Container, build_container

logger = logging.getLogger("rxd.app")


class RevalidatedStaticFiles(StaticFiles):
    """Static files that the browser re-checks on every load, so UI changes show up straight away."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response

VIEWS_DIR = Path(__file__).resolve().parent / "views"

DESCRIPTION = """
RxD helps a clinician choose a **kidney-safe dose**. The rules engine decides the dose from FDA label
rules; a small local model explains it, and every answer cites only the sources it retrieved.

**Prototype · synthetic data · not for clinical use.**

Sign in at `POST /api/v1/auth/token`, then use the **Authorize** button with the token.
"""


def create_app(
    settings: Settings | None = None,
    *,
    llm=None,
    embedder=None,
) -> FastAPI:
    """Build the app. Tests pass a FakeLLM; in normal use the container talks to Ollama."""
    settings = settings or get_settings()
    configure_logging()
    if settings.rxd_jwt_secret.startswith("change-me") or len(settings.rxd_jwt_secret) < 32:
        if settings.is_production:
            raise RuntimeError("Set RXD_JWT_SECRET to a long random value before running in production.")
        log_event(logger, "weak_jwt_secret", level=logging.WARNING,
                  hint="Set RXD_JWT_SECRET in .env to a long random string.")
    container: Container = build_container(settings, llm=llm, embedder=embedder)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        log_event(logger, "app_started", env=settings.rxd_env, model=settings.rxd_llm_model)
        yield
        log_event(logger, "app_stopped")

    app = FastAPI(
        title="RxD API",
        version="1.0.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "auth", "description": "Sign in and identity"},
            {"name": "patients", "description": "Patients and their kidney summary"},
            {"name": "intakes", "description": "Visit intakes; saved intakes are indexed for retrieval"},
            {"name": "documents", "description": "Uploaded clinical notes"},
            {"name": "chat", "description": "Chat about the selected patient"},
            {"name": "suggestions", "description": "Ask RxD and record the clinician's decision"},
            {"name": "rules", "description": "Verified renal dosing rules and label text"},
            {"name": "audit", "description": "Who did what, and when"},
            {"name": "admin", "description": "Administrative operations"},
            {"name": "health", "description": "Liveness and readiness"},
        ],
    )
    app.state.container = container
    app.state.db = container.db

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
    app.middleware("http")(request_context)
    install_error_handlers(app)

    app.mount("/static", RevalidatedStaticFiles(directory=str(VIEWS_DIR / "static")), name="static")
    app.include_router(health_router)
    app.include_router(api_v1_router, prefix="/api/v1")
    app.include_router(web_router)
    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    """Lazily build the default app, so `uvicorn app.main:app` works without building it on import."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
