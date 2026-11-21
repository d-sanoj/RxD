"""Builds the shared services once at startup: settings, database, rules catalog, model client, vector store."""

from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.models.catalog import RulesCatalog
from app.models.db import Database
from app.models.llm import ModelClient, OllamaClient
from app.models.prompts import load_master_prompt
from app.models.vector_store import VectorStore


@dataclass
class Container:
    settings: Settings
    db: Database
    catalog: RulesCatalog
    llm: ModelClient
    vector: VectorStore
    master_prompt: str


def build_container(settings: Settings, *, llm: ModelClient | None = None, embedder=None) -> Container:
    for folder in (settings.chroma_dir, settings.upload_dir, settings.eval_dir):
        Path(folder).mkdir(parents=True, exist_ok=True)
    db_url = settings.db_url
    if db_url.startswith("sqlite:///"):
        Path(db_url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)

    database = Database(db_url)
    database.create_all()
    model = llm or OllamaClient(
        base_url=settings.ollama_url,
        model=settings.rxd_llm_model,
        embed_model=settings.rxd_embed_model,
        timeout_s=settings.rxd_llm_timeout_s,
    )
    return Container(
        settings=settings,
        db=database,
        catalog=RulesCatalog.load(settings.data_path),
        llm=model,
        vector=VectorStore(settings.chroma_dir, embedder or model),
        master_prompt=load_master_prompt(settings.data_path),
    )
