"""Admin: rebuild the vector collections from the chunks table (runs in the background)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from app.controllers.deps import CurrentUser, get_container, require_roles
from app.models.admin_service import reindex
from app.models.container import Container

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reindex", status_code=202, summary="Rebuild both Chroma collections (admin)")
def start_reindex(
    background: BackgroundTasks,
    container: Annotated[Container, Depends(get_container)],
    user: Annotated[CurrentUser, Depends(require_roles("admin"))],
) -> JSONResponse:
    background.add_task(reindex, container, user.username)
    return JSONResponse(status_code=202, content={"status": "accepted", "message": "Reindex started."})
