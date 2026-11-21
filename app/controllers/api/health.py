"""Liveness (/health) and readiness (/health/ready). Readiness checks the database, Chroma and Ollama."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.controllers.deps import get_container
from app.models.container import Container
from app.views.schemas.common import Health

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health, summary="Liveness")
def liveness() -> Health:
    return Health(status="ok")


@router.get("/health/ready", response_model=Health, summary="Readiness: database, vector store, models",
            responses={503: {"description": "The database or vector store is down"}})
def readiness(
    response: Response,
    container: Annotated[Container, Depends(get_container)],
) -> Health:
    database_ok = container.db.ping()
    vectors_ok = container.vector.heartbeat()
    model = container.llm.health()
    models_ready = bool(model.get("reachable") and model.get("chat_model_pulled") and model.get("embed_model_pulled"))
    # The app still answers without Ollama (deterministic fallback), so a missing model only degrades readiness.
    if not (database_ok and vectors_ok):
        response.status_code = 503
        status = "unavailable"
    else:
        status = "ok" if models_ready else "degraded"
    return Health(status=status, checks={"database": database_ok, "vector_store": vectors_ok, "model": model})
