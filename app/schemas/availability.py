from __future__ import annotations

import uuid
from datetime import date as date_type, datetime

from pydantic import BaseModel, ConfigDict, Field


class Slot(BaseModel):
    starts_at: datetime
    ends_at: datetime


class AvailabilityRead(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "dentist_id": "00000000-0000-0000-0000-000000000000",
                "date": "2026-10-01",
                "timezone": "America/Santiago",
                "slot_minutes": 30,
                "free": [
                    {"starts_at": "2026-10-01T12:00:00Z", "ends_at": "2026-10-01T12:30:00Z"},
                    {"starts_at": "2026-10-01T12:30:00Z", "ends_at": "2026-10-01T13:00:00Z"},
                ],
            }
        }
    )

    dentist_id: uuid.UUID
    date: date_type
    timezone: str = Field(description="Zona horaria en que se interpreta el horario de atencion.")
    slot_minutes: int
    free: list[Slot] = Field(
        description="Bloques libres, en UTC. Cada uno sirve tal cual para POST /appointments."
    )
