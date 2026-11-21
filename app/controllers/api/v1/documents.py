"""Uploaded notes (pdf, txt, md, docx). Each upload is chunked and indexed; delete removes its chunks and vectors."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, UploadFile

from app.controllers.deps import CurrentUser, get_container, require_roles
from app.models.container import Container
from app.models.db import DbSession
from app.models.patient_service import PatientService
from app.views.schemas.documents import DocumentView

router = APIRouter(tags=["documents"])


@router.post("/patients/{patient_id}/documents", status_code=201, response_model=DocumentView,
             summary="Upload a note (max 5 MB; pdf, txt, md, docx)")
def upload_document(
    patient_id: str,
    file: UploadFile,
    response: Response,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    user: Annotated[CurrentUser, Depends(require_roles("clinician", "pharmacist"))],
) -> DocumentView:
    # Read one byte past the limit so the service can reject oversize files without loading them all.
    data = file.file.read(container.settings.max_upload_bytes + 1)
    document = PatientService(db, container).upload_document(
        patient_id, file.filename or "", file.content_type or "", data, user.username
    )
    response.headers["Location"] = f"/api/v1/documents/{document.id}"
    return DocumentView.model_validate(document)


@router.delete("/documents/{document_id}", status_code=204, summary="Delete a note and its vectors")
def delete_document(
    document_id: int,
    db: DbSession,
    container: Annotated[Container, Depends(get_container)],
    user: Annotated[CurrentUser, Depends(require_roles("clinician", "pharmacist"))],
) -> Response:
    PatientService(db, container).delete_document(document_id, user.username)
    return Response(status_code=204)
