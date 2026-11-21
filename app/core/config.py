"""Settings, read from environment variables and from the project's .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]  # the project folder (rxd_poc_kit)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    rxd_env: str = "dev"
    rxd_db_url: str = "sqlite:///storage/rxd.db"
    rxd_chroma_dir: Path = Path("storage/chroma")
    rxd_upload_dir: Path = Path("storage/uploads")
    rxd_data_dir: Path = Path("data")
    rxd_eval_dir: Path = Path("storage/eval")
    ollama_url: str = "http://localhost:11434"
    rxd_llm_model: str = "qwen2.5:1.5b"
    rxd_embed_model: str = "nomic-embed-text"
    rxd_llm_timeout_s: float = 60.0
    rxd_jwt_secret: str = "change-me-to-a-long-random-string"
    rxd_jwt_ttl_min: int = 60
    rxd_cors_origins: str = ""
    rxd_max_upload_mb: int = 5
    rxd_seed_pw_clinician: str = "demo-clinician"
    rxd_seed_pw_pharmacist: str = "demo-pharmacist"
    rxd_seed_pw_admin: str = "demo-admin"

    @staticmethod
    def _absolute(path: Path) -> Path:
        return path if path.is_absolute() else ROOT / path

    @property
    def db_url(self) -> str:
        prefix = "sqlite:///"
        rest = self.rxd_db_url[len(prefix):]
        if self.rxd_db_url.startswith(prefix) and not rest.startswith("/"):
            return prefix + str(ROOT / rest)
        return self.rxd_db_url

    @property
    def chroma_dir(self) -> Path:
        return self._absolute(self.rxd_chroma_dir)

    @property
    def upload_dir(self) -> Path:
        return self._absolute(self.rxd_upload_dir)

    @property
    def data_path(self) -> Path:
        return self._absolute(self.rxd_data_dir)

    @property
    def eval_dir(self) -> Path:
        return self._absolute(self.rxd_eval_dir)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.rxd_cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.rxd_max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.rxd_env.lower() in {"prod", "production"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
