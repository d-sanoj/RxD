"""Repositories: the only place where SQL is written."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import AuditEvent, Chunk, Decision, Document, Intake, Patient, Suggestion, User


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class UserRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def by_username(self, username: str) -> User | None:
        return self.db.scalar(select(User).where(User.username == username))

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        return user


class PatientRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, patient_id: str) -> Patient | None:
        return self.db.get(Patient, patient_id)

    def list(self, q: str | None = None) -> list[Patient]:
        stmt = select(Patient).order_by(Patient.id)
        if q:
            stmt = stmt.where(Patient.name.ilike(_like_pattern(q), escape="\\"))
        return list(self.db.scalars(stmt))

    def next_id(self) -> str:
        numbers = [int(pid[1:]) for pid in self.db.scalars(select(Patient.id)) if pid[1:].isdigit()]
        return f"P{(max(numbers) if numbers else 0) + 1:03d}"

    def add(self, patient: Patient) -> Patient:
        self.db.add(patient)
        self.db.flush()
        return patient


class IntakeRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, intake_id: int) -> Intake | None:
        return self.db.get(Intake, intake_id)

    def latest(self, patient_id: str) -> Intake | None:
        stmt = select(Intake).where(Intake.patient_id == patient_id).order_by(Intake.id.desc()).limit(1)
        return self.db.scalar(stmt)

    def latest_by_patient(self, patient_ids: list[str]) -> dict[str, Intake]:
        if not patient_ids:
            return {}
        newest = select(func.max(Intake.id)).where(Intake.patient_id.in_(patient_ids)).group_by(Intake.patient_id)
        rows = self.db.scalars(select(Intake).where(Intake.id.in_(newest))).all()
        return {row.patient_id: row for row in rows}

    def page(self, patient_id: str, limit: int, offset: int) -> tuple[list[Intake], int]:
        base = select(Intake).where(Intake.patient_id == patient_id)
        total = self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.db.scalars(base.order_by(Intake.id.desc()).limit(limit).offset(offset)).all()
        return list(rows), total

    def add(self, intake: Intake) -> Intake:
        self.db.add(intake)
        self.db.flush()
        return intake


class DocumentRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, document_id: int) -> Document | None:
        return self.db.get(Document, document_id)

    def for_patient(self, patient_id: str) -> list[Document]:
        stmt = select(Document).where(Document.patient_id == patient_id).order_by(Document.id)
        return list(self.db.scalars(stmt))

    def add(self, document: Document) -> Document:
        self.db.add(document)
        self.db.flush()
        return document

    def delete(self, document: Document) -> None:
        self.db.delete(document)


class ChunkRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def upsert(self, chunk: Chunk) -> Chunk:
        merged = self.db.merge(chunk)
        self.db.flush()
        return merged

    def for_patient(self, patient_id: str) -> list[Chunk]:
        stmt = select(Chunk).where(Chunk.collection == "patients", Chunk.patient_id == patient_id)
        return list(self.db.scalars(stmt.order_by(Chunk.chunk_id)))

    def for_drug(self, drug: str) -> list[Chunk]:
        stmt = select(Chunk).where(Chunk.collection == "labels", Chunk.drug == drug)
        return list(self.db.scalars(stmt.order_by(Chunk.chunk_id)))

    def by_collection(self, collection: str) -> list[Chunk]:
        return list(self.db.scalars(select(Chunk).where(Chunk.collection == collection).order_by(Chunk.chunk_id)))

    def delete_for_document(self, document_id: int) -> list[str]:
        stmt = select(Chunk).where(Chunk.kind == "upload", Chunk.ref_id == str(document_id))
        rows = list(self.db.scalars(stmt))
        ids = [row.chunk_id for row in rows]
        for row in rows:
            self.db.delete(row)
        self.db.flush()
        return ids


class SuggestionRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, suggestion_id: int) -> Suggestion | None:
        return self.db.get(Suggestion, suggestion_id)

    def page(self, limit: int, offset: int, patient_id: str | None = None) -> tuple[list[Suggestion], int]:
        base = select(Suggestion)
        if patient_id:
            base = base.where(Suggestion.patient_id == patient_id)
        total = self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.db.scalars(base.order_by(Suggestion.id.desc()).limit(limit).offset(offset)).all()
        return list(rows), total

    def add(self, suggestion: Suggestion) -> Suggestion:
        self.db.add(suggestion)
        self.db.flush()
        return suggestion


class DecisionRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def for_suggestion(self, suggestion_id: int) -> list[Decision]:
        stmt = select(Decision).where(Decision.suggestion_id == suggestion_id).order_by(Decision.id)
        return list(self.db.scalars(stmt))

    def add(self, decision: Decision) -> Decision:
        self.db.add(decision)
        self.db.flush()
        return decision


class AuditRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        user_name: str,
        action: str,
        entity: str,
        entity_id: str,
        details: dict[str, Any] | None = None,
        patient_id: str | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            user_name=user_name,
            action=action,
            entity=entity,
            entity_id=entity_id,
            patient_id=patient_id,
            details=details or {},
        )
        self.db.add(event)
        self.db.flush()
        return event

    def page(self, limit: int, offset: int, patient_id: str | None = None) -> tuple[list[AuditEvent], int]:
        base = select(AuditEvent)
        if patient_id:
            base = base.where(AuditEvent.patient_id == patient_id)
        total = self.db.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.db.scalars(base.order_by(AuditEvent.id.desc()).limit(limit).offset(offset)).all()
        return list(rows), total
