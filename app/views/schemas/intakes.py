"""Visit intake shapes. An intake is one visit's background; kidney values are computed on save."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class Medication(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["metformin"])
    dose: str = Field(default="", max_length=60, examples=["1000 mg"])
    frequency: str = Field(default="", max_length=60, examples=["twice daily"])
    model_config = ConfigDict(json_schema_extra={"example": {"name": "metformin", "dose": "1000 mg", "frequency": "twice daily"}})


class IntakeCreate(BaseModel):
    visit_date: date | None = Field(default=None, examples=["2026-11-21"])
    chief_complaint: str = Field(default="", max_length=500, examples=["Routine diabetes follow-up."])
    symptoms: str = Field(default="", max_length=2000)
    history: str = Field(default="", max_length=4000)
    conditions: list[str] = Field(default_factory=list, examples=[["Type 2 diabetes", "Hypertension"]])
    medications: list[Medication] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list, examples=[["penicillin"]])
    weight_kg: float | None = Field(default=None, gt=0, le=400, examples=[60])
    serum_creatinine_mg_dl: float | None = Field(default=None, gt=0, le=30, examples=[2.0])
    creatinine_date: date | None = Field(default=None, examples=["2026-11-09"])
    on_dialysis: bool = False
    notes: str = Field(default="", max_length=4000)
    model_config = ConfigDict(json_schema_extra={"example": {
        "chief_complaint": "Heartburn for 4 weeks, worse after meals.",
        "symptoms": "Burning chest discomfort; no alarm symptoms.",
        "conditions": ["Heartburn (symptomatic nonerosive GERD)"],
        "medications": [{"name": "lisinopril", "dose": "10 mg", "frequency": "once daily"}],
        "allergies": ["penicillin"], "weight_kg": 80, "serum_creatinine_mg_dl": 1.0,
        "creatinine_date": "2026-11-21", "on_dialysis": False, "notes": "Lives independently."}})


class IntakeView(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_extra={"example": {
        "id": 31, "patient_id": "P001", "visit_date": "2026-11-21", "recorded_by": "dr.evans",
        "chief_complaint": "Routine diabetes follow-up.", "symptoms": "", "history": "",
        "conditions": ["Type 2 diabetes on metformin"],
        "medications": [{"name": "metformin", "dose": "1000 mg", "frequency": "twice daily"}],
        "allergies": ["penicillin"], "weight_kg": 60, "serum_creatinine_mg_dl": 2.0,
        "creatinine_date": "2026-11-09", "on_dialysis": False, "notes": "",
        "crcl": 24.1, "egfr": 26.1, "ckd_stage": "G4", "flags": [],
        "created_at": "2026-11-21T09:00:00"}})

    id: int
    patient_id: str
    visit_date: date
    recorded_by: str
    chief_complaint: str
    symptoms: str
    history: str
    conditions: list[str]
    medications: list[Medication]
    allergies: list[str]
    weight_kg: float | None
    serum_creatinine_mg_dl: float | None
    creatinine_date: date | None
    on_dialysis: bool
    notes: str
    crcl: float | None
    egfr: float | None
    ckd_stage: str | None
    flags: list[str]
    created_at: datetime
