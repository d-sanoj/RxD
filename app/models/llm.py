"""Model clients. OllamaClient talks to a local Ollama server; FakeLLM is the offline stand-in for tests."""

import hashlib
import json
import logging
import math
import re
from typing import Protocol

import httpx

from app.core.logging import log_event

logger = logging.getLogger("rxd.llm")


class ModelUnavailable(Exception):
    """Ollama is down, too slow, or the model is not pulled."""


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class ModelClient(Embedder, Protocol):
    model_name: str

    def chat(self, messages: list[dict], schema: dict | None = None) -> str: ...

    def health(self) -> dict: ...


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        embed_model: str,
        timeout_s: float = 60.0,
        retries: int = 1,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model_name = model
        self.embed_model = embed_model
        self.retries = retries
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_s, transport=transport)

    def chat(self, messages: list[dict], schema: dict | None = None) -> str:
        payload: dict = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": 4096},
        }
        if schema is not None:
            payload["format"] = schema
        data = self._post("/api/chat", payload)
        return str(data.get("message", {}).get("content", ""))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = self._post("/api/embed", {"model": self.embed_model, "input": texts})
        vectors = data.get("embeddings") or []
        if len(vectors) != len(texts):
            raise ModelUnavailable("Embedding response did not match the request.")
        return vectors

    def health(self) -> dict:
        try:
            response = self._client.get("/api/tags", timeout=3.0)
            response.raise_for_status()
            names = [m.get("name", "") for m in response.json().get("models", [])]
        except (httpx.HTTPError, ValueError) as exc:
            return {"reachable": False, "chat_model_pulled": False, "embed_model_pulled": False, "error": type(exc).__name__}

        def pulled(model: str) -> bool:
            return model in names or f"{model}:latest" in names

        return {
            "reachable": True,
            "chat_model_pulled": pulled(self.model_name),
            "embed_model_pulled": pulled(self.embed_model),
        }

    def _post(self, path: str, payload: dict) -> dict:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self._client.post(path, json=payload)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                log_event(logger, "ollama_call_failed", level=logging.WARNING, path=path, attempt=attempt + 1,
                          error_type=type(exc).__name__)
        raise ModelUnavailable(f"Ollama call to {path} failed.") from last


def _hash_vector(text: str, dim: int) -> list[float]:
    vector = [0.0] * dim
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        index = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim
        vector[index] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


_RULE_LINE = re.compile(
    r"^(?P<drug>\w+): action=(?P<action>\S+?); dose=(?P<dose>.*?); max daily=(?P<max>.*?); "
    r"measure=(?P<measure>.*?); source chunks=(?P<chunks>.*)$",
    re.MULTILINE,
)


def mirror_rule(messages: list[dict]) -> dict:
    """Builds a valid answer that repeats the RULE line. Used by tests as a well-behaved model."""
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    match = _RULE_LINE.search(user)
    if not match:
        return {"drug": "unknown", "action": "insufficient_information", "recommended_dose": None,
                "max_daily_dose": None, "kidney_measure_used": None,
                "rationale": "No rule was provided.", "monitoring": None, "citations": [], "confidence": "medium"}

    def clean(value: str) -> str | None:
        value = value.strip()
        return None if value.lower() in {"none", "n/a", ""} else value

    chunk_ids = [c.strip() for c in match.group("chunks").split(",") if c.strip() and c.strip() != "none"]
    return {
        "drug": match.group("drug"),
        "action": match.group("action"),
        "recommended_dose": clean(match.group("dose")),
        "max_daily_dose": clean(match.group("max")),
        "kidney_measure_used": clean(match.group("measure")),
        "rationale": f"Follows the label rule for {match.group('drug')}: {match.group('action')}.",
        "monitoring": None,
        "citations": [{"chunk_id": cid, "quote": "cited from the label"} for cid in chunk_ids],
        "confidence": "high",
    }


class FakeLLM:
    """Offline model for tests. Replies come from `replies` first, then from mirror_rule()."""

    model_name = "fake-llm"

    def __init__(self, replies: list[str] | None = None, *, unavailable: bool = False, dim: int = 64) -> None:
        self.replies = list(replies or [])
        self.unavailable = unavailable
        self.dim = dim
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], schema: dict | None = None) -> str:
        self.calls.append(messages)
        if self.unavailable:
            raise ModelUnavailable("Fake model is switched off.")
        if self.replies:
            return self.replies.pop(0)
        return json.dumps(mirror_rule(messages))

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.unavailable:
            raise ModelUnavailable("Fake model is switched off.")
        return [_hash_vector(text, self.dim) for text in texts]

    def health(self) -> dict:
        if self.unavailable:
            return {"reachable": False, "chat_model_pulled": False, "embed_model_pulled": False}
        return {"reachable": True, "chat_model_pulled": True, "embed_model_pulled": True}
