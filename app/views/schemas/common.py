"""Shared response shapes: the standard error body, paging and health."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Patient not found."])
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str = Field(examples=["3f2b9c1e8a7d4b6f"])


class ErrorBody(BaseModel):
    """Every error from the API has this shape."""

    error: ErrorDetail
    model_config = ConfigDict(json_schema_extra={"example": {"error": {
        "code": "not_found", "message": "Patient not found.", "details": {},
        "request_id": "3f2b9c1e8a7d4b6f"}}})


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(examples=[30])
    limit: int = Field(examples=[20])
    offset: int = Field(examples=[0])


class Health(BaseModel):
    status: str = Field(examples=["ok"])
    checks: dict[str, Any] = Field(default_factory=dict)
    model_config = ConfigDict(json_schema_extra={"example": {
        "status": "ok", "checks": {"database": True, "vector_store": True,
                                   "model": {"reachable": True, "chat_model_pulled": True}}}})
