"""Audit trail queries. Events hold ids and action names only, never patient names or note text."""

from sqlalchemy.orm import Session

from app.models.entities import AuditEvent
from app.models.repositories import AuditRepo


def list_events(db: Session, limit: int, offset: int, patient_id: str | None = None) -> tuple[list[AuditEvent], int]:
    return AuditRepo(db).page(limit, offset, patient_id)
