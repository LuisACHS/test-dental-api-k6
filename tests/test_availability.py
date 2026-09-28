from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import bearer

API = settings.api_v1_prefix


def _a_future_workday() -> str:
    """Un dia habil a futuro, lejos de hoy para que no haya huecos pasados."""
    day = (datetime.now(settings.clinic_tz) + timedelta(days=21)).date()
    return day.isoformat()


async def test_dia_vacio_devuelve_toda_la_jornada(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    day = _a_future_workday()
    response = await client.get(
        f"{API}/dentists/{dentist_id}/availability",
        headers=bearer(patient_token),
        params={"date": day},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["date"] == day
    assert body["timezone"] == settings.clinic_timezone
    assert body["slot_minutes"] == settings.default_slot_minutes

    horas = settings.clinic_close_hour - settings.clinic_open_hour
    esperados = horas * 60 // settings.default_slot_minutes
    assert len(body["free"]) == esperados

    #  Los bloques son contiguos y no se pisan.
    for anterior, siguiente in zip(body["free"], body["free"][1:]):
        assert anterior["ends_at"] == siguiente["starts_at"]


async def test_una_cita_saca_su_bloque(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    day = _a_future_workday()
    url = f"{API}/dentists/{dentist_id}/availability"

    antes = (
        await client.get(url, headers=bearer(patient_token), params={"date": day})
    ).json()["free"]
    objetivo = antes[2]

    creada = await client.post(
        f"{API}/appointments",
        headers=bearer(patient_token),
        json={
            "dentist_id": dentist_id,
            "starts_at": objetivo["starts_at"],
            "ends_at": objetivo["ends_at"],
        },
    )
    assert creada.status_code == 201, creada.text

    despues = (
        await client.get(url, headers=bearer(patient_token), params={"date": day})
    ).json()["free"]
    assert len(despues) == len(antes) - 1
    assert objetivo not in despues


async def test_el_hueco_devuelto_es_reservable_tal_cual(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    """El contrato que le importa al harness: consultar y reservar sin traducir."""
    day = _a_future_workday()
    libres = (
        await client.get(
            f"{API}/dentists/{dentist_id}/availability",
            headers=bearer(patient_token),
            params={"date": day},
        )
    ).json()["free"]

    primero = libres[0]
    response = await client.post(
        f"{API}/appointments",
        headers=bearer(patient_token),
        json={
            "dentist_id": dentist_id,
            "starts_at": primero["starts_at"],
            "ends_at": primero["ends_at"],
        },
    )
    assert response.status_code == 201, response.text


async def test_slot_minutes_personalizado(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    day = _a_future_workday()
    response = await client.get(
        f"{API}/dentists/{dentist_id}/availability",
        headers=bearer(patient_token),
        params={"date": day, "slot_minutes": 60},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slot_minutes"] == 60
    assert len(body["free"]) == settings.clinic_close_hour - settings.clinic_open_hour


async def test_una_cita_larga_tapa_varios_bloques(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    day = _a_future_workday()
    url = f"{API}/dentists/{dentist_id}/availability"

    antes = (
        await client.get(url, headers=bearer(patient_token), params={"date": day})
    ).json()["free"]

    #  Dos bloques seguidos en una sola cita.
    creada = await client.post(
        f"{API}/appointments",
        headers=bearer(patient_token),
        json={
            "dentist_id": dentist_id,
            "starts_at": antes[0]["starts_at"],
            "ends_at": antes[1]["ends_at"],
        },
    )
    assert creada.status_code == 201, creada.text

    despues = (
        await client.get(url, headers=bearer(patient_token), params={"date": day})
    ).json()["free"]
    assert len(despues) == len(antes) - 2


async def test_dia_en_el_pasado_no_ofrece_nada(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    ayer = (datetime.now(settings.clinic_tz) - timedelta(days=1)).date().isoformat()
    response = await client.get(
        f"{API}/dentists/{dentist_id}/availability",
        headers=bearer(patient_token),
        params={"date": ayer},
    )
    assert response.status_code == 200
    assert response.json()["free"] == []


async def test_dentista_inexistente_da_404(client: AsyncClient, patient_token: str) -> None:
    response = await client.get(
        f"{API}/dentists/{uuid.uuid4()}/availability",
        headers=bearer(patient_token),
        params={"date": _a_future_workday()},
    )
    assert response.status_code == 404


async def test_sin_fecha_da_422(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    response = await client.get(
        f"{API}/dentists/{dentist_id}/availability", headers=bearer(patient_token)
    )
    assert response.status_code == 422


async def test_sin_token_da_401(client: AsyncClient, dentist_id: str) -> None:
    response = await client.get(
        f"{API}/dentists/{dentist_id}/availability", params={"date": _a_future_workday()}
    )
    assert response.status_code == 401
