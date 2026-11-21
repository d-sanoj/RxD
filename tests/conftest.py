"""Shared fixtures. Every test runs offline: a fake model, a temporary database and a temporary vector store."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.llm import FakeLLM  # noqa: E402
from app.models.seed_service import seed_all  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        rxd_db_url=f"sqlite:///{tmp_path / 'rxd.db'}",
        rxd_chroma_dir=tmp_path / "chroma",
        rxd_upload_dir=tmp_path / "uploads",
        rxd_eval_dir=tmp_path / "eval",
        rxd_data_dir=ROOT / "data",
        rxd_jwt_secret="test-secret-that-is-long-enough-for-hs256",
        rxd_seed_pw_clinician="pw-clinician",
        rxd_seed_pw_pharmacist="pw-pharmacist",
        rxd_seed_pw_admin="pw-admin",
    )


@pytest.fixture()
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture()
def app(settings: Settings, llm: FakeLLM):
    application = create_app(settings, llm=llm)
    seed_all(application.state.container)
    return application


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/token", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def clinician(client: TestClient, settings: Settings) -> dict[str, str]:
    return _login(client, "dr.evans", settings.rxd_seed_pw_clinician)


@pytest.fixture()
def pharmacist(client: TestClient, settings: Settings) -> dict[str, str]:
    return _login(client, "rph.aniket", settings.rxd_seed_pw_pharmacist)


@pytest.fixture()
def admin(client: TestClient, settings: Settings) -> dict[str, str]:
    return _login(client, "admin.sanoj", settings.rxd_seed_pw_admin)
