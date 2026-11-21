"""Retrieval. Labels: every chunk for the drug, in label order. Patient records: hybrid search (vector + BM25) fused with reciprocal rank fusion."""

import logging
import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session

from app.core.logging import log_event
from app.models.entities import Chunk
from app.models.llm import ModelUnavailable
from app.models.repositories import ChunkRepo
from app.models.vector_store import PATIENTS, VectorStore

logger = logging.getLogger("rxd.retrieval")

RRF_K = 60
VECTOR_TOP_N = 6
BM25_TOP_N = 6
KEEP = 4
_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class SourceChunk:
    chunk_id: str
    label: str
    text: str


@dataclass(frozen=True)
class PatientRetrieval:
    sources: list[SourceChunk]
    vector_used: bool


def _to_source(chunk: Chunk) -> SourceChunk:
    return SourceChunk(chunk_id=chunk.chunk_id, label=chunk.citation_label, text=chunk.text)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return [cid for cid, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))]


def bm25_ranking(query: str, chunks: list[Chunk], top_n: int) -> list[str]:
    if not chunks:
        return []
    corpus = [tokenize(c.text) or ["_empty_"] for c in chunks]
    scores = BM25Okapi(corpus).get_scores(tokenize(query) or ["_empty_"])
    ranked = sorted(zip(chunks, scores, strict=True), key=lambda pair: -pair[1])
    return [chunk.chunk_id for chunk, _ in ranked[:top_n]]


def retrieve_labels(db: Session, drug: str) -> list[SourceChunk]:
    return [_to_source(chunk) for chunk in ChunkRepo(db).for_drug(drug)]


def retrieve_patient(
    db: Session,
    vector: VectorStore,
    patient_id: str,
    query: str,
    latest_intake_chunk_id: str | None,
) -> PatientRetrieval:
    candidates = ChunkRepo(db).for_patient(patient_id)
    if not candidates:
        return PatientRetrieval(sources=[], vector_used=False)
    by_id = {c.chunk_id: c for c in candidates}

    rankings = [bm25_ranking(query, candidates, BM25_TOP_N)]
    vector_used = False
    try:
        vector_ids = vector.query(PATIENTS, query, where={"patient_id": patient_id}, n=VECTOR_TOP_N)
        rankings.append(vector_ids)
        vector_used = True
    except ModelUnavailable:
        log_event(logger, "vector_search_skipped", level=logging.WARNING, reason="embedding model unavailable")

    fused = [cid for cid in reciprocal_rank_fusion(rankings) if cid in by_id]
    top = fused[:KEEP]
    if latest_intake_chunk_id and latest_intake_chunk_id in by_id and latest_intake_chunk_id not in top:
        top = top[: KEEP - 1] + [latest_intake_chunk_id]
    return PatientRetrieval(sources=[_to_source(by_id[cid]) for cid in top], vector_used=vector_used)
