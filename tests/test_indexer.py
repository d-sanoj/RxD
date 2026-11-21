"""Indexing keeps working when the embedding model is down, and a rebuild never wipes vectors it cannot recreate."""

from app.models.indexer import rebuild_vectors
from app.models.llm import FakeLLM
from app.models.seed_service import seed_all


def test_seed_with_model_down_stores_text_and_skips_vectors(settings):
    from app.main import create_app

    llm = FakeLLM(unavailable=True)
    application = create_app(settings, llm=llm)
    counts = seed_all(application.state.container)
    assert counts["patients_created"] == 30
    assert counts["vectors"]["skipped"] is True
    assert counts["labels_indexed"] == 25


def test_rebuild_with_model_down_keeps_existing_vectors(settings):
    from app.main import create_app

    available = FakeLLM()
    application = create_app(settings, llm=available)
    container = application.state.container
    seed_all(container)
    before = container.vector._collection("labels").count()
    assert before == 25

    container.llm.unavailable = True  # the same object is also the embedder
    session = container.db.session_factory()
    try:
        result = rebuild_vectors(session, container.vector)
    finally:
        session.close()
    assert result["skipped"] is True
    assert container.vector._collection("labels").count() == before
