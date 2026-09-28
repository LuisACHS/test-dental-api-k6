from __future__ import annotations

from datetime import datetime, timedelta

from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import bearer, future_slot

API = settings.api_v1_prefix


async def test_crear_cita(client: AsyncClient, patient_token: str, dentist_id: str) -> None:
    starts_at, ends_at = future_slot()

    response = await client.post(
        f"{API}/appointments",
        headers=bearer(patient_token),
        json={
            "dentist_id": dentist_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "reason": "Control semestral",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["dentist_id"] == dentist_id

    listed = await client.get(f"{API}/appointments", headers=bearer(patient_token))
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]

    detail = await client.get(f"{API}/appointments/{body['id']}", headers=bearer(patient_token))
    assert detail.status_code == 200


async def test_cita_solapada_da_409(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    """Lo garantiza el EXCLUDE constraint de la base, no un SELECT previo."""
    starts_at, ends_at = future_slot(minutes=60)
    payload = {"dentist_id": dentist_id, "starts_at": starts_at, "ends_at": ends_at}

    assert (
        await client.post(f"{API}/appointments", headers=bearer(patient_token), json=payload)
    ).status_code == 201

    #  Se solapa a medias con la anterior.
    overlapping = dict(
        payload,
        starts_at=(datetime.fromisoformat(starts_at) + timedelta(minutes=30)).isoformat(),
        ends_at=(datetime.fromisoformat(ends_at) + timedelta(minutes=30)).isoformat(),
    )
    response = await client.post(
        f"{API}/appointments", headers=bearer(patient_token), json=overlapping
    )
    assert response.status_code == 409, response.text


async def test_citas_contiguas_no_chocan(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    """El rango es '[)': 14:00-14:30 y 14:30-15:00 conviven."""
    starts_at, ends_at = future_slot(minutes=30)
    first = {"dentist_id": dentist_id, "starts_at": starts_at, "ends_at": ends_at}
    second = {
        "dentist_id": dentist_id,
        "starts_at": ends_at,
        "ends_at": (datetime.fromisoformat(ends_at) + timedelta(minutes=30)).isoformat(),
    }

    assert (
        await client.post(f"{API}/appointments", headers=bearer(patient_token), json=first)
    ).status_code == 201
    assert (
        await client.post(f"{API}/appointments", headers=bearer(patient_token), json=second)
    ).status_code == 201


async def test_cita_en_el_pasado_da_400(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    starts_at, ends_at = future_slot(days_ahead=-30)
    response = await client.post(
        f"{API}/appointments",
        headers=bearer(patient_token),
        json={"dentist_id": dentist_id, "starts_at": starts_at, "ends_at": ends_at},
    )
    assert response.status_code == 400


async def test_cita_mas_corta_que_el_minimo_da_400(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    starts_at, ends_at = future_slot(minutes=1)
    response = await client.post(
        f"{API}/appointments",
        headers=bearer(patient_token),
        json={"dentist_id": dentist_id, "starts_at": starts_at, "ends_at": ends_at},
    )
    assert response.status_code == 400


async def test_cita_sin_zona_horaria_da_422(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    response = await client.post(
        f"{API}/appointments",
        headers=bearer(patient_token),
        json={
            "dentist_id": dentist_id,
            "starts_at": "2030-01-01T10:00:00",
            "ends_at": "2030-01-01T10:30:00",
        },
    )
    assert response.status_code == 422


async def test_cita_sin_token_da_401(client: AsyncClient, dentist_id: str) -> None:
    starts_at, ends_at = future_slot()
    response = await client.post(
        f"{API}/appointments",
        json={"dentist_id": dentist_id, "starts_at": starts_at, "ends_at": ends_at},
    )
    assert response.status_code == 401


async def test_paciente_no_ve_la_cita_de_otro(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    starts_at, ends_at = future_slot()
    created = await client.post(
        f"{API}/appointments",
        headers=bearer(patient_token),
        json={"dentist_id": dentist_id, "starts_at": starts_at, "ends_at": ends_at},
    )
    assert created.status_code == 201
    appointment_id = created.json()["id"]

    other = await client.post(
        f"{API}/auth/register",
        json={"email": f"otro-{appointment_id[:8]}@dental.local", "password": "otro-password-123"},
    )
    assert other.status_code == 201
    login = await client.post(
        f"{API}/auth/login",
        data={"username": other.json()["email"], "password": "otro-password-123"},
    )
    other_token = login.json()["access_token"]

    response = await client.get(
        f"{API}/appointments/{appointment_id}", headers=bearer(other_token)
    )
    assert response.status_code == 404


async def test_paciente_no_puede_crear_dentista(client: AsyncClient, patient_token: str) -> None:
    response = await client.post(
        f"{API}/dentists", headers=bearer(patient_token), json={"full_name": "Dr. Intruso"}
    )
    assert response.status_code == 403


async def test_admin_crea_dentista(client: AsyncClient, admin_token: str) -> None:
    response = await client.post(
        f"{API}/dentists",
        headers=bearer(admin_token),
        json={"full_name": "Dra. Ana Soto", "specialty": "Ortodoncia"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["specialty"] == "Ortodoncia"
