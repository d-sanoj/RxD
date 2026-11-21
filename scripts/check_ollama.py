"""Confirms Ollama is running and the two models are pulled. Exits with 1 if not.

    python scripts/check_ollama.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.models.llm import OllamaClient  # noqa: E402


def main() -> int:
    settings = get_settings()
    client = OllamaClient(settings.ollama_url, settings.rxd_llm_model, settings.rxd_embed_model)
    status = client.health()
    print(f"Ollama at {settings.ollama_url}: {'reachable' if status.get('reachable') else 'NOT reachable'}")
    print(f"  chat model  {settings.rxd_llm_model}: {'pulled' if status.get('chat_model_pulled') else 'missing'}")
    print(f"  embed model {settings.rxd_embed_model}: {'pulled' if status.get('embed_model_pulled') else 'missing'}")
    if status.get("reachable") and status.get("chat_model_pulled") and status.get("embed_model_pulled"):
        print("All good.")
        return 0
    print("RxD still runs without Ollama (rules-only answers, marked 'fallback'). To enable the model:")
    print(f"  ollama pull {settings.rxd_llm_model}")
    print(f"  ollama pull {settings.rxd_embed_model}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
