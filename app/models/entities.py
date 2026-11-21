"""ORM entities (SQLAlchemy 2.0 typed mappings)."""

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # naive UTC, as SQLite stores it


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))  # clinician | pharmacist | admin
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # "P001"
    name: Mapped[str] = mapped_column(String(120))
    sex: Mapped[str | None] = mapped_column(String(1), nullable=True)  # "F" | "M"
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    allergies: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    intakes: Mapped[list["Intake"]] = relationship(
        back_populates="patient", order_by="Intake.id", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="patient", order_by="Document.id", cascade="all, delete-orphan"
    )


class Intake(Base):
    """One visit intake. Kidney values are computed when it is saved and stored."""

    __tablename__ = "intakes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    visit_date: Mapped[date] = mapped_column(Date)
    recorded_by: Mapped[str] = mapped_column(String(64))
    chief_complaint: Mapped[str] = mapped_column(Text, default="")
    symptoms: Mapped[str] = mapped_column(Text, default="")
    history: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    medications: Mapped[list] = mapped_column(JSON, default=list)  # [{name, dose, frequency}]
    allergies: Mapped[list] = mapped_column(JSON, default=list)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    serum_creatinine_mg_dl: Mapped[float | None] = mapped_column(Float, nullable=True)
    creatinine_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    on_dialysis: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    crcl: Mapped[float | None] = mapped_column(Float, nullable=True)
    egfr: Mapped[float | None] = mapped_column(Float, nullable=True)
    ckd_stage: Mapped[str | None] = mapped_column(String(4), nullable=True)
    flags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped[Patient] = relationship(back_populates="intakes")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120), default="")
    storage_path: Mapped[str] = mapped_column(String(512))
    uploaded_by: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)

    patient: Mapped[Patient] = relationship(back_populates="documents")


class Chunk(Base):
    """Text of every retrievable chunk. Keyword search reads it; Chroma holds the vectors."""

    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    collection: Mapped[str] = mapped_column(String(16), index=True)  # patients | labels
    patient_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    drug: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # intake | upload | label
    ref_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    citation_label: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    intake_id: Mapped[int | None] = mapped_column(ForeignKey("intakes.id"), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    drug: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rule_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # snapshot: [{chunk_id, label, text}]
    retrieved_ids: Mapped[list] = mapped_column(JSON, default=list)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_output: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))  # ok | needs_review | blocked | fallback
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="suggestion", order_by="Decision.id", cascade="all, delete-orphan"
    )


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(ForeignKey("suggestions.id"), index=True)
    decision: Mapped[str] = mapped_column(String(10))  # accept | edit | reject
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(64))
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    suggestion: Mapped[Suggestion] = relationship(back_populates="decisions")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_name: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    patient_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
