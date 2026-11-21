"""Patient shapes: the list card, the create body and the detail page."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.views.schemas.documents import DocumentView
from app.views.schemas.intakes import IntakeView


class KidneyView(BaseModel):
    egfr: float | None = Field(examples=[26.1])
    crcl: float | None = Field(examples=[24.1])
    ckd_stage: str | None = Field(examples=["G4"])
    flags: list[str] = Field(default_factory=list, examples=[["stale_lab"]])
    creatinine_date: date | None = Field(default=None, examples=["2026-11-09"])
    lab_age_days: int | None = Field(default=None, examples=[12])
    dialysis: bool = False
    model_config = ConfigDict(json_schema_extra={"example": {
        "egfr": 26.1, "crcl": 24.1, "ckd_stage": "G4", "flags": [], "creatinine_date": "2026-11-09",
        "lab_age_days": 12, "dialysis": False}})


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Test Patient (synthetic)"])
    sex: str | None = Field(default=None, pattern="^[FM]$", examples=["F"])
    age: int | None = Field(default=None, ge=0, le=120, examples=[50])
    height_cm: float | None = Field(default=None, gt=0, le=250, examples=[165])
    allergies: list[str] = Field(default_factory=list, examples=[["sulfa drugs"]])
    model_config = ConfigDict(json_schema_extra={"example": {
        "name": "Test Patient (synthetic)", "sex": "M", "age": 50, "height_cm": 178, "allergies": []}})


class PatientSummary(BaseModel):
    id: str = Field(examples=["P001"])
    name: str = Field(examples=["Maria Lopez (synthetic)"])
    sex: str | None = Field(default=None, examples=["F"])
    age: int | None = Field(default=None, examples=[72])
    height_cm: float | None = Field(default=None, examples=[158])
    allergies: list[str] = Field(default_factory=list)
    latest_visit_date: date | None = Field(default=None, examples=["2026-11-21"])
    egfr: float | None = Field(default=None, examples=[26.1])
    crcl: float | None = Field(default=None, examples=[24.1])
    ckd_stage: str | None = Field(default=None, examples=["G4"])
    flags: list[str] = Field(default_factory=list)
    model_config = ConfigDict(json_schema_extra={"example": {
        "id": "P001", "name": "Maria Lopez (synthetic)", "sex": "F", "age": 72, "height_cm": 158,
        "allergies": ["penicillin"], "latest_visit_date": "2026-11-21", "egfr": 26.1, "crcl": 24.1,
        "ckd_stage": "G4", "flags": []}})


class PatientDetail(BaseModel):
    id: str = Field(examples=["P001"])
    name: str = Field(examples=["Maria Lopez (synthetic)"])
    sex: str | None = Field(default=None, examples=["F"])
    age: int | None = Field(default=None, examples=[72])
    height_cm: float | None = None
    allergies: list[str] = Field(default_factory=list)
    latest_intake: IntakeView | None = None
    kidney: KidneyView | None = None
    documents: list[DocumentView] = Field(default_factory=list)
