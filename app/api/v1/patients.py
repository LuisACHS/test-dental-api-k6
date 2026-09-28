from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from app.core.deps import CurrentAdmin, CurrentUser, DbSession, get_user_by_email
from app.core.security import hash_password
from app.models.appointment import Appointment, AppointmentStatus
from app.models.user import User, UserRole
from app.schemas.appointment import AppointmentRead
from app.schemas.patient import PatientCreate, PatientRead, PatientUpdate

router = APIRouter(prefix="/patients", tags=["patients"])


async def _get_patient(db: DbSession, patient_id: uuid.UUID) -> User:
    """Un paciente es un User con role=patient: un admin no cuenta como tal."""
    patient = await db.get(User, patient_id)
    if patient is None or patient.role is not UserRole.patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado")
    return patient


def _check_self_or_admin(current_user: User, patient_id: uuid.UUID) -> None:
    if current_user.role is not UserRole.admin and current_user.id != patient_id:
        #  404 y no 403: un 403 confirmaria que el paciente existe.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paciente no encontrado")


@router.post(
    "",
    response_model=PatientRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un paciente (admin)",
    responses={409: {"description": "El email ya esta registrado."}},
)
async def create_patient(
    payload: PatientCreate,
    db: DbSession,
    _: CurrentAdmin,
) -> User:
    if await get_user_by_email(db, payload.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="El email ya esta registrado"
        )

    hashed = await run_in_threadpool(hash_password, payload.password)
    patient = User(
        email=payload.email,
        hashed_password=hashed,
        full_name=payload.full_name,
        role=UserRole.patient,
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)
    return patient


@router.get("", response_model=list[PatientRead], summary="Listar pacientes (admin)")
async def list_patients(
    db: DbSession,
    _: CurrentAdmin,
    only_active: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[User]:
    stmt = (
        select(User)
        .where(User.role == UserRole.patient)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if only_active:
        stmt = stmt.where(User.is_active.is_(True))
    result = await db.scalars(stmt)
    return list(result)


@router.get("/{patient_id}", response_model=PatientRead, summary="Detalle de un paciente")
async def get_patient(
    patient_id: uuid.UUID,
    db: DbSession,
    current_user: CurrentUser,
) -> User:
    _check_self_or_admin(current_user, patient_id)
    return await _get_patient(db, patient_id)


@router.patch("/{patient_id}", response_model=PatientRead, summary="Editar un paciente")
async def update_patient(
    patient_id: uuid.UUID,
    payload: PatientUpdate,
    db: DbSession,
    current_user: CurrentUser,
) -> User:
    _check_self_or_admin(current_user, patient_id)
    patient = await _get_patient(db, patient_id)

    changes = payload.model_dump(exclude_unset=True)

    if "is_active" in changes and current_user.role is not UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un admin puede activar o desactivar un paciente",
        )

    if "email" in changes and changes["email"] != patient.email:
        existing = await get_user_by_email(db, changes["email"])
        if existing is not None and existing.id != patient.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="El email ya esta registrado"
            )

    for field, value in changes.items():
        setattr(patient, field, value)

    await db.commit()
    await db.refresh(patient)
    return patient


@router.get(
    "/{patient_id}/appointments",
    response_model=list[AppointmentRead],
    summary="Citas de un paciente",
)
async def list_patient_appointments(
    patient_id: uuid.UUID,
    db: DbSession,
    current_user: CurrentUser,
    dentist_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[AppointmentStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Appointment]:
    _check_self_or_admin(current_user, patient_id)
    await _get_patient(db, patient_id)

    stmt = (
        select(Appointment)
        .where(Appointment.patient_id == patient_id)
        .order_by(Appointment.starts_at)
        .limit(limit)
        .offset(offset)
    )
    if dentist_id is not None:
        stmt = stmt.where(Appointment.dentist_id == dentist_id)
    if status_filter is not None:
        stmt = stmt.where(Appointment.status == status_filter)

    result = await db.scalars(stmt)
    return list(result)
