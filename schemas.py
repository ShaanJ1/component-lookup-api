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
    description:    str | None = Field(..., description="A brief description of the component", examples=["A Precision Timer IC", "8-bit Microcontroller with 32KB Flash", "General Purpose Diode"])
    specifications: dict[str, Any] = Field(..., default_factory=dict, description="The listed specifications of the component in key-value format", examples=["""{"total supply current": "8mA", "operating temperature": "-55°C to +125°C", "package": "DIP-8"}"""])
    datasheet_url:  HttpUrl = Field(..., description="URL to the component's datasheet", examples=["https://datasheet.datasheetarchive.com/originals/distributors/Datasheets-5/DSA-98723.pdf"])
    source:         str = Field(..., max_length=100, description="Source of the component information/datasheet", examples=["datasheetarchive"])

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
        str_strip_whitespace = True,  # Strip whitespace from string fields
        json_schema_extra = {
            "example": {
                "description": "Precision Timer IC",
                "specifications": {
                    "Supply Voltage": "4.5V - 16V",
                    "Operating Temperature": "-55°C to +125°C",
                    "Package": "DIP-8",
                    "Pins": "8"
                },
                "datasheet_url": "https://example.com/datasheet.pdf",
                "source": "Updated source information"
            }
        }
    )

    description:    str | None = None
    specifications: dict[str, Any] | None = None
    datasheet_url:  HttpUrl | None = None
    source:         str | None = None

    @field_validator("description", "source", mode="before")
    @classmethod
    def sanitize_fields(cls, value):
        return sanitize_text(value) if value else value
