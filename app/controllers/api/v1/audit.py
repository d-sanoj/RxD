"""Audit trail (pharmacist and admin)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.controllers.deps import CurrentUser, get_container, require_roles
from app.models.audit_service import list_events
from app.models.container import Container
from app.models.db import DbSession
from app.views.schemas.audit import AuditEventView
from app.views.schemas.common import Page

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=Page[AuditEventView], summary="Audit events, newest first")
def get_audit(
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    _user: Annotated[CurrentUser, Depends(require_roles("pharmacist", "admin"))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    patient_id: Annotated[str | None, Query(max_length=16)] = None,
) -> Page[AuditEventView]:
    rows, total = list_events(db, limit, offset, patient_id)
    return Page[AuditEventView](
        items=[AuditEventView.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )
