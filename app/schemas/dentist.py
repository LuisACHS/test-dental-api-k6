from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DentistCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"full_name": "Dra. Ana Soto", "specialty": "Ortodoncia"}
        }
    )

    full_name: str = Field(min_length=2, max_length=200)
    specialty: str | None = Field(default=None, max_length=120)
    is_active: bool = True


class DentistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    specialty: str | None
    is_active: bool
    created_at: datetime
