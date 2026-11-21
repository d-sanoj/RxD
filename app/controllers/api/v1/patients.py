"""Patients: list (worst kidney function first), create, and detail."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.controllers.deps import CurrentUser, current_user, get_container, require_roles
from app.models.container import Container
from app.models.db import DbSession
from app.models.patient_service import PatientService
from app.views.schemas.common import Page
from app.views.schemas.patients import PatientCreate, PatientDetail, PatientSummary

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("", response_model=Page[PatientSummary], summary="List patients, worst kidney function first")
def list_patients(
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    _user: Annotated[CurrentUser, Depends(current_user)],
    q: Annotated[str | None, Query(max_length=120)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[PatientSummary]:
    items, total = PatientService(db, container).list_cards(q, limit, offset)
    return Page[PatientSummary](
        items=[PatientSummary.model_validate(item) for item in items], total=total, limit=limit, offset=offset
    )


@router.post("", status_code=201, response_model=PatientSummary, summary="Create a patient")
def create_patient(
    body: PatientCreate,
    response: Response,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    user: Annotated[CurrentUser, Depends(require_roles("clinician"))],
) -> PatientSummary:
    card = PatientService(db, container).create_patient(body.model_dump(), user.username)
    response.headers["Location"] = f"/api/v1/patients/{card['id']}"
    return PatientSummary.model_validate(card)


@router.get("/{patient_id}", response_model=PatientDetail, summary="Patient with latest intake, kidney values and documents")
def get_patient(
    patient_id: str,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    _user: Annotated[CurrentUser, Depends(current_user)],
) -> PatientDetail:
    return PatientDetail.model_validate(PatientService(db, container).get_detail(patient_id))
