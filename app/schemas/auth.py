from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.user import UserRole

#  Validacion de email con regex en vez de EmailStr: `EmailStr` obliga a
#  instalar email-validator, que arrastra dnspython. Para un login basta esto.
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=5,
        max_length=320,
        pattern=_EMAIL_PATTERN,
    ),
]

#  72 bytes es el limite real de bcrypt; se rechaza arriba en vez de truncar
#  en silencio.
Password = Annotated[str, StringConstraints(min_length=8, max_length=72)]


class UserCreate(BaseModel):
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


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Segundos de vida del token.")
