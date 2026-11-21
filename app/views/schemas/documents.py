"""Uploaded note shapes."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_extra={"example": {
        "id": 4, "patient_id": "P001", "filename": "discharge-note.txt", "content_type": "text/plain",
        "uploaded_by": "dr.evans", "uploaded_at": "2026-11-21T10:12:00", "chunk_count": 2}})

    id: int
    patient_id: str
    filename: str = Field(examples=["discharge-note.txt"])
    content_type: str
    uploaded_by: str
    uploaded_at: datetime
    chunk_count: int
