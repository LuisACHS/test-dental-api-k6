from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.models.appointment import NO_OVERLAP_CONSTRAINT, Appointment, AppointmentStatus
from app.models.dentist import Dentist
from app.models.user import User, UserRole
from app.schemas.appointment import AppointmentCreate, AppointmentRead

router = APIRouter(prefix="/appointments", tags=["appointments"])

#  Codigos SQLSTATE de Postgres que nos interesa distinguir.
_SQLSTATE_EXCLUSION_VIOLATION = "23P01"
_SQLSTATE_FOREIGN_KEY_VIOLATION = "23503"


def _sqlstate(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def _is_overlap_violation(exc: IntegrityError) -> bool:
    if _sqlstate(exc) == _SQLSTATE_EXCLUSION_VIOLATION:
        return True
    #  Respaldo por si el driver no propaga el sqlstate.
    return NO_OVERLAP_CONSTRAINT in str(getattr(exc, "orig", exc))


@router.post(
    "",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una cita",
    responses={
        409: {"description": "El dentista ya tiene una cita que se superpone con ese horario."}
    },
)
async def create_appointment(
    payload: AppointmentCreate,
    db: DbSession,
    current_user: CurrentUser,
) -> Appointment:
    patient_id = await _resolve_patient_id(payload, db, current_user)
    _validate_schedule(payload)

    dentist = await db.get(Dentist, payload.dentist_id)
    if dentist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dentista no encontrado")
    if not dentist.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="El dentista no esta activo"
        )

    appointment = Appointment(
        patient_id=patient_id,
        dentist_id=payload.dentist_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        reason=payload.reason,
        status=AppointmentStatus.scheduled,
    )
    db.add(appointment)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        #  El no-solape lo garantiza un EXCLUDE constraint en la base, no un
        #  SELECT previo: bajo concurrencia un chequeo en Python tiene una
        #  ventana de carrera y produce dobles reservas.
        if _is_overlap_violation(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El dentista ya tiene una cita en ese horario",
            ) from exc
        if _sqlstate(exc) == _SQLSTATE_FOREIGN_KEY_VIOLATION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Paciente o dentista inexistente",
            ) from exc
        raise

    await db.refresh(appointment)
    return appointment


@router.get("", response_model=list[AppointmentRead], summary="Listar citas")
async def list_appointments(
    db: DbSession,
    current_user: CurrentUser,
    dentist_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[AppointmentStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Appointment]:
    stmt = select(Appointment).order_by(Appointment.starts_at).limit(limit).offset(offset)

    #  Un paciente solo ve lo suyo; el admin ve todo.
    if current_user.role is not UserRole.admin:
        stmt = stmt.where(Appointment.patient_id == current_user.id)
    if dentist_id is not None:
        stmt = stmt.where(Appointment.dentist_id == dentist_id)
    if status_filter is not None:
        stmt = stmt.where(Appointment.status == status_filter)

    result = await db.scalars(stmt)
    return list(result)


@router.get("/{appointment_id}", response_model=AppointmentRead, summary="Detalle de una cita")
async def get_appointment(
    appointment_id: uuid.UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> Appointment:
    appointment = await db.get(Appointment, appointment_id)
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cita no encontrada")
    if current_user.role is not UserRole.admin and appointment.patient_id != current_user.id:
        #  404 y no 403: un 403 confirmaria que la cita existe.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cita no encontrada")
    return appointment


async def _resolve_patient_id(
    payload: AppointmentCreate, db: DbSession, current_user: User
) -> uuid.UUID:
    if payload.patient_id is None or payload.patient_id == current_user.id:
        return current_user.id

    if current_user.role is not UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un admin puede agendar a nombre de otro paciente",
        )
    if await db.get(User, payload.patient_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado")
    return payload.patient_id


def _validate_schedule(payload: AppointmentCreate) -> None:
    minutes = (payload.ends_at - payload.starts_at).total_seconds() / 60
    if minutes < settings.min_appointment_minutes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La cita debe durar al menos {settings.min_appointment_minutes} minutos",
        )
    if minutes > settings.max_appointment_minutes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La cita no puede durar mas de {settings.max_appointment_minutes} minutos",
        )
    if not settings.allow_past_appointments and payload.starts_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La cita debe ser a futuro (ver ALLOW_PAST_APPOINTMENTS)",
        )
