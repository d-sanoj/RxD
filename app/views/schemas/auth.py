"""Auth response shapes."""

from pydantic import BaseModel, ConfigDict, Field


class Token(BaseModel):
    access_token: str = Field(examples=["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."])
    token_type: str = Field(default="bearer", examples=["bearer"])
    expires_in: int = Field(examples=[3600])
    model_config = ConfigDict(json_schema_extra={"example": {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...", "token_type": "bearer", "expires_in": 3600}})


class Me(BaseModel):
    username: str = Field(examples=["dr.evans"])
    role: str = Field(examples=["clinician"])
    model_config = ConfigDict(json_schema_extra={"example": {"username": "dr.evans", "role": "clinician"}})
