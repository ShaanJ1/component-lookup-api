# Typed Pydantic models

from pydantic import BaseModel, Field
from typing import Any
from datetime import datetime

class ComponentBase(BaseModel):
    part_number:    str
    description:    str | None = None
    specifications: dict[str, Any] | None = Field(default_factory=dict)
    datasheet_url:  str
    source:         str


class ComponentResponse(ComponentBase):
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ComponentHistoryResponse(ComponentBase):
    saved_at: datetime

    class Config:
        from_attributes = True

class ComponentUpdate(BaseModel):
    description:    str | None = None
    specifications: dict[str, Any] | None = None
    datasheet_url:  str | None = None
    source:         str | None = None


