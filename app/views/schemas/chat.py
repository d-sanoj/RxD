"""Chat request and reply shapes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.views.schemas.suggestions import SourceView, SuggestionView


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    patient_id: str = Field(examples=["P001"])
    message: str = Field(min_length=1, max_length=1000, examples=["What is her kidney function?"])
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)
    model_config = ConfigDict(json_schema_extra={"example": {
        "patient_id": "P001", "message": "What medications is she on?", "history": []}})


class ChatReply(BaseModel):
    kind: Literal["dosing", "record", "info"] = Field(examples=["record"])
    answer: str
    sources: list[SourceView] = Field(default_factory=list)
    suggestion: SuggestionView | None = None
    offline: bool = False
    model_name: str | None = None
    latency_ms: int = 0
    model_config = ConfigDict(json_schema_extra={"example": {
        "kind": "record", "answer": "Her eGFR is 26.1 (stage G4). [PT-P001-intake-1]",
        "sources": [], "suggestion": None, "offline": False, "model_name": "qwen2.5:1.5b", "latency_ms": 820}})
