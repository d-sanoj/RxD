"""Suggestions: ask RxD about a drug, read a suggestion or the history, and record the clinician's decision."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.controllers.deps import CurrentUser, current_user, get_container, require_roles
from app.models.container import Container
from app.models.db import DbSession
from app.models.rxd_service import RxdService
from app.views.schemas.common import Page
from app.views.schemas.suggestions import DecisionCreate, DecisionView, SuggestionCreate, SuggestionView

router = APIRouter(tags=["suggestions"])


@router.post("/suggestions", status_code=201, response_model=SuggestionView, summary="Ask RxD about a drug")
def create_suggestion(
    body: SuggestionCreate,
    response: Response,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    user: Annotated[CurrentUser, Depends(require_roles("clinician", "pharmacist"))],
) -> SuggestionView:
    suggestion = RxdService(db, container).create_suggestion(
        patient_id=body.patient_id, question=body.question, actor=user.username
    )
    response.headers["Location"] = f"/api/v1/suggestions/{suggestion.id}"
    return SuggestionView.model_validate(suggestion)


@router.get("/suggestions/{suggestion_id}", response_model=SuggestionView, summary="One suggestion")
def get_suggestion(
    suggestion_id: int,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    _user: Annotated[CurrentUser, Depends(current_user)],
) -> SuggestionView:
    return SuggestionView.model_validate(RxdService(db, container).get_suggestion(suggestion_id))


@router.get("/patients/{patient_id}/suggestions", response_model=Page[SuggestionView],
            summary="Suggestion history for a patient, newest first")
def list_patient_suggestions(
    patient_id: str,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    _user: Annotated[CurrentUser, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[SuggestionView]:
    items, total = RxdService(db, container).list_for_patient(patient_id, limit, offset)
    return Page[SuggestionView](
        items=[SuggestionView.model_validate(s) for s in items], total=total, limit=limit, offset=offset
    )


@router.post("/suggestions/{suggestion_id}/decision", status_code=201, response_model=DecisionView,
             summary="Accept, edit or reject a suggestion")
def record_decision(
    suggestion_id: int,
    body: DecisionCreate,
    response: Response,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    user: Annotated[CurrentUser, Depends(require_roles("clinician"))],
) -> DecisionView:
    decision = RxdService(db, container).record_decision(
        suggestion_id=suggestion_id, decision=body.decision, edited_text=body.edited_text,
        reason=body.reason, actor=user.username,
    )
    response.headers["Location"] = f"/api/v1/suggestions/{suggestion_id}"
    return DecisionView.model_validate(decision)
