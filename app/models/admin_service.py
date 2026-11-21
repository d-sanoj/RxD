"""Admin operations. Reindexing rebuilds the Chroma collections from the chunks table."""

from app.models.container import Container
from app.models.indexer import rebuild_vectors
from app.models.repositories import AuditRepo


def reindex(container: Container, actor: str) -> dict:
    session = container.db.session_factory()
    try:
        counts = rebuild_vectors(session, container.vector)
        AuditRepo(session).add(actor, "admin.reindex", "index", "patients+labels", counts)
        session.commit()
        return counts
    finally:
        session.close()
