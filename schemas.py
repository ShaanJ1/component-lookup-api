# Typed Pydantic models

from pydantic import BaseModel, Field, field_validator, HttpUrl, ConfigDict
from typing import Any
from datetime import datetime
import re
from loguru import logger

def sanitize_text(text: str | None) -> str | None:
    """
    Sanitizes the input text by removing unwanted characters and formatting it.
    """
    if text is None:
        return None
    
    text = text.strip()
    return re.compile(r'<[^>]+>').sub('', text)  # Remove HTML tags and other unwanted characters


class ComponentBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",  # Forbid extra fields not defined in the model
        str_strip_whitespace = True  # Strip whitespace from string fields
    )

    part_number:    str = Field(..., min_length=1, max_length=100, description="The unique part number of the component", examples=["NE555", "ATmega328P", "1N4148"])
    description:    str | None = Field(..., description="Component description")
    specifications: dict[str, Any] = Field(..., default_factory=dict, description="Component specifications")
    datasheet_url:  HttpUrl = Field(..., description="URL of the component's datasheet")
    source:         str = Field(..., max_length=100, description="Source of the component information")

    @field_validator("part_number", mode="before")
    @classmethod
    def validate_part_number(cls, value):
        logger.trace(f"Validating part number: {value}")
        if not isinstance(value, str):
            raise ValueError("Part number must be a non-empty string.")
        
        value = sanitize_text(value).upper()

        if not re.fullmatch(r'^[A-Z0-9._/\-]+', value):
            raise ValueError("Invalid Part Number Format.")
        
        return value

    @field_validator("description", "source", mode="before")
    @classmethod
    def sanitize_fields(cls, value):
        return sanitize_text(value) if value else value

class ComponentResponse(ComponentBase):
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ComponentHistoryResponse(ComponentBase):
    saved_at: datetime

    class Config:
        from_attributes = True


# purposely not including part_number, created_at, updated_at so they cannot be changed
class ComponentUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",  # Forbid extra fields not defined in the model
        str_strip_whitespace = True  # Strip whitespace from string fields
    )
        
    description:    str | None = None
    specifications: dict[str, Any] | None = None
    datasheet_url:  HttpUrl | None = None
    source:         str | None = None

    @field_validator("description", "source", mode="before")
    @classmethod
    def sanitize_fields(cls, value):
        return sanitize_text(value) if value else value
