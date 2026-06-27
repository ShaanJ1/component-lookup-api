# PostgreSQL Database Models

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, DateTime
from datetime import datetime
from database import Base
from typing import Any

from database import engine

class ComponentModel(Base):
    __tablename__ = "component"
    part_number:    Mapped[str] = mapped_column(primary_key=True, unique=True, index=True)
    description:    Mapped[str | None]
    specifications: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    datasheet_url:  Mapped[str]
    source:         Mapped[str]

    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ComponentHistoryModel(Base):
    __tablename__ = "component_history"

    id:             Mapped[int] = mapped_column(primary_key=True, autoincrement=True) # id auto increments so multiple versions of the same part can exist
    part_number:    Mapped[str] = mapped_column(index=True)
    description:    Mapped[str | None]
    specifications: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    datasheet_url:  Mapped[str]
    source:         Mapped[str]

    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(engine)