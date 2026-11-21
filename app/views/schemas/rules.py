"""Rules shapes: each drug's label chunks and whether a pharmacist has verified the rule."""

from pydantic import BaseModel, ConfigDict, Field


class RuleChunk(BaseModel):
    chunk_id: str = Field(examples=["LBL-metformin-04"])
    text: str


class RuleView(BaseModel):
    drug: str = Field(examples=["metformin"])
    product: str
    measure: str = Field(examples=["eGFR"])
    source: str
    verified_by: str | None = Field(default=None, examples=[None])
    verified: bool = Field(examples=[False])
    chunks: list[RuleChunk]
    model_config = ConfigDict(json_schema_extra={"example": {
        "drug": "metformin", "product": "Metformin Hydrochloride Tablets, USP", "measure": "eGFR",
        "source": "openFDA drug label API, retrieved 2026-11-21", "verified_by": None, "verified": False,
        "chunks": [{"chunk_id": "LBL-metformin-04", "text": "Discontinue if eGFR falls below 30."}]}})


class RuleList(BaseModel):
    items: list[RuleView]
