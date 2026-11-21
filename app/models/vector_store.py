"""Chroma wrapper with two collections: "patients" and "labels"."""

import os
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb  # noqa: E402

from app.models.llm import Embedder  # noqa: E402

PATIENTS = "patients"
LABELS = "labels"


class VectorStore:
    def __init__(self, path: Path, embedder: Embedder) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.embedder = embedder

    def _collection(self, name: str):
        return self.client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    def upsert(self, collection: str, ids: list[str], texts: list[str], metadatas: list[dict]) -> None:
        if not ids:
            return
        vectors = self.embedder.embed(texts)  # raises ModelUnavailable when Ollama is down
        self._collection(collection).upsert(ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas)

    def delete(self, collection: str, ids: list[str]) -> None:
        if ids:
            self._collection(collection).delete(ids=ids)

    def query(self, collection: str, text: str, where: dict, n: int) -> list[str]:
        col = self._collection(collection)
        available = col.count()
        if available == 0:
            return []
        vector = self.embedder.embed([text])[0]
        result = col.query(query_embeddings=[vector], n_results=min(n, available), where=where)
        return list(result["ids"][0])

    def reset(self, collection: str) -> None:
        try:
            self.client.delete_collection(collection)
        except Exception:  # the collection did not exist yet
            pass

    def heartbeat(self) -> bool:
        try:
            self.client.heartbeat()
            return True
        except Exception:
            return False
