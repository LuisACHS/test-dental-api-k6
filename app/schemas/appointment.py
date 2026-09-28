from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models.appointment import AppointmentStatus


class AppointmentCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "dentist_id": "00000000-0000-0000-0000-000000000000",
                "starts_at": "2026-10-01T14:00:00Z",
                "ends_at": "2026-10-01T14:30:00Z",
                "reason": "Control semestral",
            }
        }
    )

    dentist_id: uuid.UUID
    #  AwareDatetime obliga a mandar zona horaria: sin ella el rango que se
    #  compara en la base queda ambiguo.
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: str | None = Field(default=None, max_length=500)
    #  Solo un admin puede agendar a nombre de otro; para un paciente se ignora.
    patient_id: uuid.UUID | None = Field(
        default=None, description="Solo admin. Un paciente siempre agenda para si mismo."
    )

    @model_validator(mode="after")
    def _check_range(self) -> "AppointmentCreate":
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at debe ser anterior a ends_at")
        return self


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    dentist_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    reason: str | None
    created_at: datetime
