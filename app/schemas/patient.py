from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import Email, Password


class PatientCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "paciente@dental.local",
                "password": "paciente12345",
                "full_name": "Paciente de Prueba",
            }
        }
    )

    email: Email
    password: Password
    full_name: str | None = Field(default=None, max_length=200)


class PatientUpdate(BaseModel):
    """Todos los campos son opcionales: solo se aplica lo que venga en el body.

    `is_active` solo lo puede tocar un admin; la ruta lo valida.
    """

    model_config = ConfigDict(
        json_schema_extra={"example": {"full_name": "Juan Perez Actualizado"}}
    )

    email: Email | None = None
    full_name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class PatientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    created_at: datetime
