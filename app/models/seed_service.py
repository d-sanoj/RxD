"""Idempotent seeding: demo users, the 30 synthetic patients with one intake each, and the label chunks."""

import json
import logging
import re
from datetime import date, timedelta

from app.core.logging import log_event
from app.core.security import hash_password
from app.models.container import Container
from app.models.entities import Intake, Patient, User
from app.models.indexer import index_intake, index_labels, rebuild_vectors
from app.models.kidney import assess
from app.models.repositories import IntakeRepo, PatientRepo, UserRepo

logger = logging.getLogger("rxd.seed")

# The synthetic records were generated with this date; later seeds shift creatinine dates forward.
DATASET_DATE = date(2026, 11, 21)
DEMO_USERS = [
    ("dr.evans", "clinician", "rxd_seed_pw_clinician"),
    ("rph.aniket", "pharmacist", "rxd_seed_pw_pharmacist"),
    ("admin.sanoj", "admin", "rxd_seed_pw_admin"),
]
_MEDICATION = re.compile(
    r"^(?P<name>.+?)\s+(?P<dose>\d+(?:\.\d+)?\s*(?:mg|mcg|g|mL|units?))\s*(?P<frequency>.*)$", re.IGNORECASE
)


def parse_medication(text: str) -> dict:
    match = _MEDICATION.match(text.strip())
    if match:
        return {"name": match.group("name").strip(), "dose": match.group("dose").strip(),
                "frequency": match.group("frequency").strip()}
    return {"name": text.strip(), "dose": "", "frequency": ""}


def seed_users(container: Container) -> int:
    settings = container.settings
    session = container.db.session_factory()
    created = 0
    try:
        repo = UserRepo(session)
        for username, role, password_setting in DEMO_USERS:
            if repo.by_username(username) is None:
                repo.add(User(username=username, password_hash=hash_password(getattr(settings, password_setting)),
                              role=role, active=True))
                created += 1
        session.commit()
    finally:
        session.close()
    return created


def seed_patients(container: Container) -> int:
    records = json.loads((container.settings.data_path / "patients" / "synthetic_patients.json")
                         .read_text(encoding="utf-8"))
    shift = (date.today() - DATASET_DATE).days
    session = container.db.session_factory()
    created = 0
    try:
        patients = PatientRepo(session)
        for record in records:
            if patients.get(record["id"]) is not None:
                continue
            patient = patients.add(Patient(
                id=record["id"],
                name=record["name"],
                sex=record["sex"],
                age=record["age"],
                height_cm=record.get("height_cm"),
                allergies=list(record.get("allergies") or []),
            ))
            scr = record.get("scr")
            creatinine_date = (date.fromisoformat(record["scr_date"]) + timedelta(days=shift)) if scr is not None else None
            today = date.today()
            dialysis = bool(record.get("dialysis"))
            kidney = assess(age=patient.age, sex=patient.sex, weight_kg=record.get("weight_kg"), scr=scr,
                            creatinine_date=creatinine_date, on_dialysis=dialysis, today=today)
            visits = record.get("visits") or [{}]
            intake = IntakeRepo(session).add(Intake(
                patient_id=patient.id,
                visit_date=today,
                recorded_by="seed",
                chief_complaint=visits[0].get("chief_complaint", ""),
                symptoms="",
                history="",
                conditions=list(record.get("conditions") or []),
                medications=[parse_medication(m) for m in record.get("medications") or []],
                allergies=list(record.get("allergies") or []),
                weight_kg=record.get("weight_kg"),
                serum_creatinine_mg_dl=scr,
                creatinine_date=creatinine_date,
                on_dialysis=dialysis,
                notes=record.get("background", ""),
                crcl=kidney.crcl,
                egfr=kidney.egfr,
                ckd_stage=kidney.ckd_stage,
                flags=kidney.flags,
            ))
            index_intake(session, container.vector, patient, intake)
            created += 1
        session.commit()
    finally:
        session.close()
    return created


def seed_labels(container: Container) -> int:
    session = container.db.session_factory()
    try:
        count = index_labels(session, container.vector, container.catalog)
        session.commit()
        return count
    finally:
        session.close()


def seed_all(container: Container) -> dict:
    counts = {
        "users_created": seed_users(container),
        "patients_created": seed_patients(container),
        "labels_indexed": seed_labels(container),
    }
    # Make sure the vectors exist once the model is reachable (a no-op with Ollama down).
    session = container.db.session_factory()
    try:
        counts["vectors"] = rebuild_vectors(session, container.vector)
        session.commit()
    finally:
        session.close()
    log_event(logger, "seed_complete", **{k: v for k, v in counts.items() if not isinstance(v, dict)})
    return counts
