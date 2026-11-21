"""Patients, visit intakes and uploaded notes. Kidney values are computed here and stored with each intake."""

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UnprocessableError
from app.models.chunking import ALLOWED_UPLOAD_EXTENSIONS, chunk_text, extract_text
from app.models.container import Container
from app.models.entities import Document, Intake, Patient
from app.models.indexer import index_document, index_intake, remove_document
from app.models.kidney import assess
from app.models.repositories import AuditRepo, DocumentRepo, IntakeRepo, PatientRepo


class PatientService:
    def __init__(self, db: Session, container: Container) -> None:
        self.db = db
        self.c = container

    # ----- helpers -----
    def _patient_or_404(self, patient_id: str) -> Patient:
        patient = PatientRepo(self.db).get(patient_id)
        if patient is None:
            raise NotFoundError("Patient not found.")
        return patient

    @staticmethod
    def kidney_for(patient: Patient, intake: Intake | None, today: date) -> dict | None:
        if intake is None:
            return None
        k = assess(
            age=patient.age,
            sex=patient.sex,
            weight_kg=intake.weight_kg,
            scr=intake.serum_creatinine_mg_dl,
            creatinine_date=intake.creatinine_date,
            on_dialysis=intake.on_dialysis,
            today=today,
        )
        return {
            "egfr": k.egfr,
            "crcl": k.crcl,
            "ckd_stage": k.ckd_stage,
            "flags": k.flags,
            "creatinine_date": intake.creatinine_date,
            "lab_age_days": k.lab_age_days,
            "dialysis": intake.on_dialysis,
        }

    def _card(self, patient: Patient, intake: Intake | None, today: date) -> dict:
        kidney = self.kidney_for(patient, intake, today) or {}
        return {
            "id": patient.id,
            "name": patient.name,
            "sex": patient.sex,
            "age": patient.age,
            "height_cm": patient.height_cm,
            "allergies": list(patient.allergies or []),
            "latest_visit_date": intake.visit_date if intake else None,
            "egfr": kidney.get("egfr"),
            "crcl": kidney.get("crcl"),
            "ckd_stage": kidney.get("ckd_stage"),
            "flags": kidney.get("flags", []),
        }

    # ----- patients -----
    def list_cards(self, q: str | None, limit: int, offset: int) -> tuple[list[dict], int]:
        patients = PatientRepo(self.db).list(q)
        latest = IntakeRepo(self.db).latest_by_patient([p.id for p in patients])
        today = date.today()
        cards = [self._card(p, latest.get(p.id), today) for p in patients]
        # worst kidney function first; patients without an intake last
        cards.sort(key=lambda c: (c["egfr"] is None, c["egfr"] or 0, c["name"]))
        return cards[offset:offset + limit], len(cards)

    def create_patient(self, data: dict, actor: str) -> dict:
        repo = PatientRepo(self.db)
        patient = repo.add(
            Patient(
                id=repo.next_id(),
                name=data["name"].strip(),
                sex=data.get("sex"),
                age=data.get("age"),
                height_cm=data.get("height_cm"),
                allergies=list(data.get("allergies") or []),
            )
        )
        AuditRepo(self.db).add(actor, "patient.create", "patient", patient.id, patient_id=patient.id)
        self.db.commit()
        return self._card(patient, None, date.today())

    def get_detail(self, patient_id: str) -> dict:
        patient = self._patient_or_404(patient_id)
        intake = IntakeRepo(self.db).latest(patient_id)
        return {
            "id": patient.id,
            "name": patient.name,
            "sex": patient.sex,
            "age": patient.age,
            "height_cm": patient.height_cm,
            "allergies": list(patient.allergies or []),
            "latest_intake": intake,
            "kidney": self.kidney_for(patient, intake, date.today()),
            "documents": DocumentRepo(self.db).for_patient(patient_id),
        }

    # ----- intakes -----
    def record_intake(self, patient_id: str, data: dict, actor: str) -> Intake:
        patient = self._patient_or_404(patient_id)
        today = date.today()
        scr = data.get("serum_creatinine_mg_dl")
        creatinine_date = data.get("creatinine_date") or (today if scr is not None else None)
        on_dialysis = bool(data.get("on_dialysis"))
        kidney = assess(
            age=patient.age,
            sex=patient.sex,
            weight_kg=data.get("weight_kg"),
            scr=scr,
            creatinine_date=creatinine_date,
            on_dialysis=on_dialysis,
            today=today,
        )
        intake = IntakeRepo(self.db).add(
            Intake(
                patient_id=patient.id,
                visit_date=data.get("visit_date") or today,
                recorded_by=actor,
                chief_complaint=data.get("chief_complaint") or "",
                symptoms=data.get("symptoms") or "",
                history=data.get("history") or "",
                conditions=list(data.get("conditions") or []),
                medications=list(data.get("medications") or []),
                allergies=list(data.get("allergies") or []),
                weight_kg=data.get("weight_kg"),
                serum_creatinine_mg_dl=scr,
                creatinine_date=creatinine_date,
                on_dialysis=on_dialysis,
                notes=data.get("notes") or "",
                crcl=kidney.crcl,
                egfr=kidney.egfr,
                ckd_stage=kidney.ckd_stage,
                flags=kidney.flags,
            )
        )
        index_intake(self.db, self.c.vector, patient, intake)
        AuditRepo(self.db).add(actor, "intake.create", "intake", str(intake.id), patient_id=patient.id)
        self.db.commit()
        return intake

    def list_intakes(self, patient_id: str, limit: int, offset: int) -> tuple[list[Intake], int]:
        self._patient_or_404(patient_id)
        return IntakeRepo(self.db).page(patient_id, limit, offset)

    def get_intake(self, patient_id: str, intake_id: int) -> Intake:
        intake = IntakeRepo(self.db).get(intake_id)
        if intake is None or intake.patient_id != patient_id:
            raise NotFoundError("Intake not found.")
        return intake

    # ----- documents -----
    def upload_document(self, patient_id: str, filename: str, content_type: str, data: bytes, actor: str) -> Document:
        patient = self._patient_or_404(patient_id)
        suffix = Path(filename or "").suffix.lower()
        if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
            raise UnprocessableError("Only pdf, txt, md and docx files can be uploaded.", code="unsupported_file_type")
        if len(data) > self.c.settings.max_upload_bytes:
            raise UnprocessableError(
                f"Files must be {self.c.settings.rxd_max_upload_mb} MB or smaller.", code="file_too_large"
            )
        try:
            text = extract_text(suffix, data)
        except Exception as exc:
            raise UnprocessableError("The file could not be read.", code="unreadable_file") from exc
        pieces = chunk_text(text)
        if not pieces:
            raise UnprocessableError("No readable text was found in the file.", code="no_text")

        document = DocumentRepo(self.db).add(
            Document(
                patient_id=patient.id,
                filename=Path(filename).name[:255],
                content_type=content_type or "",
                storage_path="",
                uploaded_by=actor,
                chunk_count=len(pieces),
            )
        )
        stored = self.c.settings.upload_dir / f"{document.id:06d}{suffix}"
        stored.write_bytes(data)
        document.storage_path = stored.name
        index_document(self.db, self.c.vector, patient.id, document, pieces)
        AuditRepo(self.db).add(actor, "document.upload", "document", str(document.id),
                               {"chunks": len(pieces)}, patient_id=patient.id)
        self.db.commit()
        return document

    def delete_document(self, document_id: int, actor: str) -> None:
        repo = DocumentRepo(self.db)
        document = repo.get(document_id)
        if document is None:
            raise NotFoundError("Document not found.")
        patient_id, stored_name = document.patient_id, document.storage_path
        remove_document(self.db, self.c.vector, document.id)
        repo.delete(document)
        AuditRepo(self.db).add(actor, "document.delete", "document", str(document_id), patient_id=patient_id)
        self.db.commit()
        stored = self.c.settings.upload_dir / stored_name
        if stored_name and stored.exists():
            stored.unlink()
