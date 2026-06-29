# PostgreSQL Database Models

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, DateTime, TypeDecorator, String
from datetime import datetime
from database import Base
from typing import Any
from pydantic import HttpUrl

from loguru import logger

from database import engine

# Custom SQLAlchemy TypeDecorator for Pydantics HttpUrl type
class HttpUrlType(TypeDecorator):
    impl = String(2083)
    cache_ok = True
    python_type = HttpUrl

    def process_bind_param(self, value, dialect) -> str:
        return str(value)
    
    def process_result_value(self, value, dialect) -> HttpUrl:
        return HttpUrl(value)
    
    def process_literal_param(self, value, dialect) -> str:
        return str(value)

class ComponentModel(Base):
    __tablename__ = "component"
    part_number:    Mapped[str] = mapped_column(primary_key=True, unique=True, index=True)
    description:    Mapped[str | None]
    specifications: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    datasheet_url:  Mapped[HttpUrl] = mapped_column(HttpUrlType)
    source:         Mapped[str]

    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ComponentHistoryModel(Base):
    __tablename__ = "component_history"

    id:             Mapped[int] = mapped_column(primary_key=True, autoincrement=True) # id auto increments so multiple versions of the same part can exist
    part_number:    Mapped[str] = mapped_column(index=True)
    description:    Mapped[str | None]
    specifications: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    datasheet_url:  Mapped[HttpUrl] = mapped_column(HttpUrlType)
    source:         Mapped[str]

    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


Base.metadata.create_all(engine)
logger.success("Database tables verified/created")