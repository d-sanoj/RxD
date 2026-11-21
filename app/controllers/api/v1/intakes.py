"""Visit intakes: record one (computes kidney values and indexes it for retrieval), list history, get one."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.controllers.deps import CurrentUser, current_user, get_container, require_roles
from app.models.container import Container
from app.models.db import DbSession
from app.models.patient_service import PatientService
from app.views.schemas.common import Page
from app.views.schemas.intakes import IntakeCreate, IntakeView

router = APIRouter(prefix="/patients/{patient_id}/intakes", tags=["intakes"])


@router.post("", status_code=201, response_model=IntakeView, summary="Record a visit intake")
def create_intake(
    patient_id: str,
    body: IntakeCreate,
    response: Response,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    user: Annotated[CurrentUser, Depends(require_roles("clinician"))],
) -> IntakeView:
    intake = PatientService(db, container).record_intake(patient_id, body.model_dump(), user.username)
    response.headers["Location"] = f"/api/v1/patients/{patient_id}/intakes/{intake.id}"
    return IntakeView.model_validate(intake)


@router.get("", response_model=Page[IntakeView], summary="Visit history, newest first")
def list_intakes(
    patient_id: str,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    _user: Annotated[CurrentUser, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IntakeView]:
    items, total = PatientService(db, container).list_intakes(patient_id, limit, offset)
    return Page[IntakeView](items=[IntakeView.model_validate(i) for i in items], total=total, limit=limit, offset=offset)


@router.get("/{intake_id}", response_model=IntakeView, summary="One visit intake")
def get_intake(
    patient_id: str,
    intake_id: int,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    _user: Annotated[CurrentUser, Depends(current_user)],
) -> IntakeView:
    return IntakeView.model_validate(PatientService(db, container).get_intake(patient_id, intake_id))
