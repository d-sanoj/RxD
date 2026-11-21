"""Chat about the selected patient. The patient id comes from the request, so the message never names them."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.controllers.deps import CurrentUser, get_container, require_roles
from app.models.chat_service import ChatService
from app.models.container import Container
from app.models.db import DbSession
from app.views.schemas.chat import ChatReply, ChatRequest

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatReply, summary="Ask the assistant about the selected patient")
def chat(
    body: ChatRequest,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    user: Annotated[CurrentUser, Depends(require_roles("clinician", "pharmacist"))],
) -> ChatReply:
    result = ChatService(db, container).reply(
        patient_id=body.patient_id,
        message=body.message,
        history=[turn.model_dump() for turn in body.history],
        actor=user.username,
    )
    return ChatReply.model_validate(result)
