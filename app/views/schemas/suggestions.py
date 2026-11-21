"""Suggestion shapes: the question, the cited answer, and the clinician's decision."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SuggestionCreate(BaseModel):
    patient_id: str = Field(examples=["P001"])
    question: str = Field(min_length=3, max_length=500, examples=["Is metformin 1000 mg twice daily still OK?"])
    model_config = ConfigDict(json_schema_extra={"example": {
        "patient_id": "P001", "question": "Is metformin 1000 mg twice daily still OK?"}})


class SourceView(BaseModel):
    chunk_id: str = Field(examples=["LBL-metformin-04"])
    label: str = Field(examples=["FDA label · Metformin Hydrochloride Tablets, USP"])
    text: str


class CitationView(BaseModel):
    chunk_id: str = Field(examples=["LBL-metformin-04"])
    quote: str


class FinalOutput(BaseModel):
    drug: str = Field(examples=["metformin"])
    action: str = Field(examples=["avoid"])
    recommended_dose: str | None = None
    max_daily_dose: str | None = None
    kidney_measure_used: str | None = Field(default=None, examples=["eGFR"])
    rationale: str
    monitoring: str | None = None
    citations: list[CitationView] = Field(default_factory=list)
    confidence: str = Field(examples=["high"])
    model_config = ConfigDict(json_schema_extra={"example": {
        "drug": "metformin", "action": "avoid", "recommended_dose": None, "max_daily_dose": None,
        "kidney_measure_used": "eGFR",
        "rationale": "The patient already takes metformin and eGFR is 26.1, below 30. The label says to discontinue.",
        "monitoring": "Stop metformin and agree an alternative glucose-lowering plan.",
        "citations": [{"chunk_id": "LBL-metformin-04", "quote": "Discontinue if eGFR falls below 30"}],
        "confidence": "high"}})


class DecisionView(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_extra={"example": {
        "id": 2, "suggestion_id": 7, "decision": "accept", "edited_text": None, "reason": None,
        "decided_by": "dr.evans", "decided_at": "2026-11-21T10:20:00"}})

    id: int
    suggestion_id: int
    decision: str
    edited_text: str | None
    reason: str | None
    decided_by: str
    decided_at: datetime


class SuggestionView(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_extra={"example": {
        "id": 7, "patient_id": "P001", "intake_id": 1, "question": "Is metformin 1000 mg twice daily still OK?",
        "drug": "metformin", "status": "needs_review",
        "final_output": FinalOutput.model_config["json_schema_extra"]["example"],
        "rule_result": {"drug": "metformin", "action": "avoid"},
        "sources": [{"chunk_id": "LBL-metformin-04", "label": "FDA label · Metformin", "text": "Discontinue if eGFR falls below 30."}],
        "model_name": "qwen2.5:1.5b", "model_output": None, "latency_ms": 412,
        "created_by": "dr.evans", "created_at": "2026-11-21T10:15:00", "decisions": []}})

    id: int
    patient_id: str
    intake_id: int | None
    question: str
    drug: str | None
    status: str = Field(examples=["ok"])
    final_output: dict[str, Any]
    rule_result: dict[str, Any] | None
    sources: list[SourceView]
    model_name: str | None
    model_output: dict[str, Any] | None
    latency_ms: int
    created_by: str
    created_at: datetime
    decisions: list[DecisionView] = Field(default_factory=list)


class DecisionCreate(BaseModel):
    decision: Literal["accept", "edit", "reject"]
    edited_text: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=1000)
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"decision": "accept"},
        {"decision": "edit", "edited_text": "Stop metformin; review with the patient today."},
        {"decision": "reject", "reason": "Patient already stopped metformin last week."},
    ]})
