"""Writes chunk text to the chunks table and vectors to Chroma. If the embedding model is down,
the text is still stored, so keyword search keeps working and a later reindex fills the vectors in."""

import logging

from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.models.catalog import RulesCatalog
from app.models.chunking import document_chunk_id, intake_chunk_id, intake_text
from app.models.entities import Chunk, Document, Intake, Patient
from app.models.llm import ModelUnavailable
from app.models.repositories import ChunkRepo
from app.models.vector_store import LABELS, PATIENTS, VectorStore

logger = logging.getLogger("rxd.indexer")
BATCH = 32


def _vector_upsert(vector: VectorStore, collection: str, chunks: list[Chunk]) -> bool:
    try:
        vector.upsert(
            collection,
            [c.chunk_id for c in chunks],
            [c.text for c in chunks],
            [{"patient_id": c.patient_id or "", "drug": c.drug or "", "kind": c.kind, "ref_id": c.ref_id or ""}
             for c in chunks],
        )
        return True
    except ModelUnavailable as exc:
        log_event(logger, "vector_index_skipped", level=logging.WARNING, collection=collection, reason=str(exc))
        return False


def index_intake(db: Session, vector: VectorStore, patient: Patient, intake: Intake) -> bool:
    chunk = Chunk(
        chunk_id=intake_chunk_id(patient.id, intake.id),
        collection=PATIENTS,
        patient_id=patient.id,
        drug=None,
        kind="intake",
        ref_id=str(intake.id),
        citation_label=f"Visit intake · {intake.visit_date.isoformat()}",
        text=intake_text(
            visit_date=intake.visit_date.isoformat(),
            patient_name=patient.name,
            age=patient.age,
            sex=patient.sex,
            chief_complaint=intake.chief_complaint,
            symptoms=intake.symptoms,
            history=intake.history,
            conditions=list(intake.conditions or []),
            medications=list(intake.medications or []),
            allergies=list(intake.allergies or []),
            weight_kg=intake.weight_kg,
            scr=intake.serum_creatinine_mg_dl,
            creatinine_date=intake.creatinine_date.isoformat() if intake.creatinine_date else None,
            on_dialysis=intake.on_dialysis,
            notes=intake.notes,
        ),
    )
    ChunkRepo(db).upsert(chunk)
    return _vector_upsert(vector, PATIENTS, [chunk])


def index_document(db: Session, vector: VectorStore, patient_id: str, document: Document, pieces: list[str]) -> bool:
    chunks = []
    for n, piece in enumerate(pieces, start=1):
        chunk = Chunk(
            chunk_id=document_chunk_id(patient_id, document.id, n),
            collection=PATIENTS,
            patient_id=patient_id,
            drug=None,
            kind="upload",
            ref_id=str(document.id),
            citation_label=f"Uploaded note · {document.filename}",
            text=piece,
        )
        ChunkRepo(db).upsert(chunk)
        chunks.append(chunk)
    return _vector_upsert(vector, PATIENTS, chunks) if chunks else True


def remove_document(db: Session, vector: VectorStore, document_id: int) -> None:
    ids = ChunkRepo(db).delete_for_document(document_id)
    try:
        vector.delete(PATIENTS, ids)
    except ModelUnavailable as exc:
        log_event(logger, "vector_delete_skipped", level=logging.WARNING, reason=str(exc))


def index_labels(db: Session, vector: VectorStore, catalog: RulesCatalog) -> int:
    chunks = []
    for label in catalog.all_labels():
        chunk = Chunk(
            chunk_id=label.chunk_id,
            collection=LABELS,
            patient_id=None,
            drug=label.drug,
            kind="label",
            ref_id=None,
            citation_label=f"FDA label · {label.product}",
            text=label.text,
        )
        ChunkRepo(db).upsert(chunk)
        chunks.append(chunk)
    _vector_upsert(vector, LABELS, chunks)
    return len(chunks)


def rebuild_vectors(db: Session, vector: VectorStore) -> dict:
    """Rebuild both Chroma collections from the chunks table. Returns counts.

    If the embedding model is down, nothing is reset, so existing vectors are kept."""
    counts = {"indexed": 0, "failed": 0}
    try:
        vector.embedder.embed(["connectivity check"])
    except ModelUnavailable as exc:
        log_event(logger, "reindex_skipped", level=logging.WARNING, reason=str(exc))
        counts["failed"] = len(ChunkRepo(db).by_collection(PATIENTS)) + len(ChunkRepo(db).by_collection(LABELS))
        counts["skipped"] = True
        return counts
    for collection in (PATIENTS, LABELS):
        vector.reset(collection)
        rows = ChunkRepo(db).by_collection(collection)
        for start in range(0, len(rows), BATCH):
            batch = rows[start:start + BATCH]
            if _vector_upsert(vector, collection, batch):
                counts["indexed"] += len(batch)
            else:
                counts["failed"] += len(batch)
    return counts
