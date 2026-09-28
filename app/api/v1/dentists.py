from __future__ import annotations

import uuid
from datetime import date as date_type, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentAdmin, CurrentUser, DbSession
from app.models.appointment import Appointment, AppointmentStatus
from app.models.dentist import Dentist
from app.schemas.availability import AvailabilityRead, Slot
from app.schemas.dentist import DentistCreate, DentistRead

router = APIRouter(prefix="/dentists", tags=["dentists"])


@router.get("", response_model=list[DentistRead], summary="Listar dentistas")
async def list_dentists(
    db: DbSession,
    _: CurrentUser,
    only_active: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Dentist]:
    stmt = select(Dentist).order_by(Dentist.full_name).limit(limit).offset(offset)
    if only_active:
        stmt = stmt.where(Dentist.is_active.is_(True))
    result = await db.scalars(stmt)
    return list(result)


@router.post(
    "",
    response_model=DentistRead,
    status_code=status.HTTP_201_CREATED,
    summary="Crear dentista (admin)",
)
async def create_dentist(
    payload: DentistCreate,
    db: DbSession,
    _: CurrentAdmin,
) -> Dentist:
    dentist = Dentist(**payload.model_dump())
    db.add(dentist)
    await db.commit()
    await db.refresh(dentist)
    return dentist


@router.get("/{dentist_id}", response_model=DentistRead, summary="Detalle de dentista")
async def get_dentist(dentist_id: uuid.UUID, db: DbSession, _: CurrentUser) -> Dentist:
    dentist = await db.get(Dentist, dentist_id)
    if dentist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dentista no encontrado")
    return dentist


@router.get(
    "/{dentist_id}/availability",
    response_model=AvailabilityRead,
    summary="Huecos libres de un dentista en un dia",
    description=(
        "Devuelve los bloques libres dentro del horario de atencion, ya "
        "descontadas las citas existentes. Los bloques vienen en UTC y se "
        "pueden mandar tal cual a `POST /appointments`. "
        "El horario de atencion sale de `CLINIC_OPEN_HOUR`, `CLINIC_CLOSE_HOUR` "
        "y `CLINIC_TIMEZONE`."
    ),
)
async def get_availability(
    dentist_id: uuid.UUID,
    db: DbSession,
    _: CurrentUser,
    date: Annotated[date_type, Query(description="Dia a consultar, YYYY-MM-DD.")],
    slot_minutes: Annotated[int | None, Query(ge=5, le=480)] = None,
) -> AvailabilityRead:
    dentist = await db.get(Dentist, dentist_id)
    if dentist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dentista no encontrado")

    step = timedelta(minutes=slot_minutes or settings.default_slot_minutes)
    day_start, day_end = _clinic_window(date)

    #  Una sola consulta, apoyada en el indice (dentist_id, starts_at). Las
    #  canceladas no ocupan: el mismo criterio que usa el EXCLUDE constraint.
    rows = await db.execute(
        select(Appointment.starts_at, Appointment.ends_at)
        .where(
            Appointment.dentist_id == dentist_id,
            Appointment.status != AppointmentStatus.cancelled,
            Appointment.starts_at < day_end,
            Appointment.ends_at > day_start,
        )
        .order_by(Appointment.starts_at)
    )
    #  El EXCLUDE constraint garantiza que no se solapan entre si, asi que la
    #  lista viene ordenada y disjunta y basta recorrerla una vez.
    busy = rows.all()

    return AvailabilityRead(
        dentist_id=dentist_id,
        date=date,
        timezone=settings.clinic_timezone,
        slot_minutes=int(step.total_seconds() // 60),
        free=_free_slots(day_start, day_end, step, busy),
    )


def _clinic_window(day: date_type) -> tuple[datetime, datetime]:
    """Apertura y cierre del dia, como instantes absolutos."""
    midnight = datetime.combine(day, time(0), tzinfo=settings.clinic_tz)
    #  Sumar horas a partir de medianoche en vez de construir time(hour=...)
    #  permite que CLINIC_CLOSE_HOUR sea 24.
    return (
        midnight + timedelta(hours=settings.clinic_open_hour),
        midnight + timedelta(hours=settings.clinic_close_hour),
    )


def _free_slots(
    day_start: datetime,
    day_end: datetime,
    step: timedelta,
    busy: list[tuple[datetime, datetime]],
) -> list[Slot]:
    now = datetime.now(timezone.utc)
    free: list[Slot] = []
    cursor = day_start
    index = 0

    while cursor + step <= day_end:
        slot_end = cursor + step

        #  Las citas que ya terminaron antes del cursor no vuelven a mirarse:
        #  el recorrido es lineal, no cuadratico.
        while index < len(busy) and busy[index][1] <= cursor:
            index += 1

        occupied = index < len(busy) and busy[index][0] < slot_end
        in_the_past = not settings.allow_past_appointments and cursor < now
        if not occupied and not in_the_past:
            #  Se emite en UTC, igual que el resto de la API: el mismo instante,
            #  pero un solo formato para quien consume.
            free.append(
                Slot(
                    starts_at=cursor.astimezone(timezone.utc),
                    ends_at=slot_end.astimezone(timezone.utc),
                )
            )

        cursor = slot_end

    return free
