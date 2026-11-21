"""Audit event shape."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_extra={"example": {
        "id": 12, "at": "2026-11-21T10:15:00", "user_name": "dr.evans", "action": "suggestion.create",
        "entity": "suggestion", "entity_id": "7", "patient_id": "P001", "details": {"drug": "metformin"}}})

    id: int
    at: datetime
    user_name: str = Field(examples=["dr.evans"])
    action: str = Field(examples=["suggestion.create"])
    entity: str
    entity_id: str
    patient_id: str | None
    details: dict[str, Any]
