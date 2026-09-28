from __future__ import annotations

from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import bearer, future_slot, unique_email

API = settings.api_v1_prefix


async def _patient_id(client: AsyncClient, token: str) -> str:
    me = await client.get(f"{API}/auth/me", headers=bearer(token))
    assert me.status_code == 200
    return me.json()["id"]


async def test_admin_crea_lista_y_ve_detalle_de_paciente(
    client: AsyncClient, admin_token: str
) -> None:
    email = unique_email("nuevo-paciente")
    created = await client.post(
        f"{API}/patients",
        headers=bearer(admin_token),
        json={"email": email, "password": "un-password-valido", "full_name": "Juan Perez"},
    )
    assert created.status_code == 201, created.text
    patient_id = created.json()["id"]
    assert created.json()["email"] == email

    listed = await client.get(f"{API}/patients", headers=bearer(admin_token))
    assert listed.status_code == 200
    assert patient_id in [item["id"] for item in listed.json()]

    detail = await client.get(f"{API}/patients/{patient_id}", headers=bearer(admin_token))
    assert detail.status_code == 200
    assert detail.json()["full_name"] == "Juan Perez"


async def test_crear_paciente_duplicado_da_409(client: AsyncClient, admin_token: str) -> None:
    payload = {"email": unique_email(), "password": "un-password-valido"}
    assert (
        await client.post(f"{API}/patients", headers=bearer(admin_token), json=payload)
    ).status_code == 201
    assert (
        await client.post(f"{API}/patients", headers=bearer(admin_token), json=payload)
    ).status_code == 409


async def test_paciente_no_puede_crear_ni_listar_pacientes(
    client: AsyncClient, patient_token: str
) -> None:
    assert (
        await client.post(
            f"{API}/patients",
            headers=bearer(patient_token),
            json={"email": unique_email(), "password": "un-password-valido"},
        )
    ).status_code == 403
    assert (await client.get(f"{API}/patients", headers=bearer(patient_token))).status_code == 403


async def test_paciente_ve_y_edita_su_propio_registro(
    client: AsyncClient, patient_token: str
) -> None:
    patient_id = await _patient_id(client, patient_token)

    detail = await client.get(f"{API}/patients/{patient_id}", headers=bearer(patient_token))
    assert detail.status_code == 200

    updated = await client.patch(
        f"{API}/patients/{patient_id}",
        headers=bearer(patient_token),
        json={"full_name": "Nombre Actualizado"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["full_name"] == "Nombre Actualizado"


async def test_paciente_no_ve_ni_edita_a_otro_paciente(
    client: AsyncClient, patient_token: str, admin_token: str
) -> None:
    email = unique_email("otro")
    other = await client.post(
        f"{API}/patients",
        headers=bearer(admin_token),
        json={"email": email, "password": "un-password-valido"},
    )
    other_id = other.json()["id"]

    assert (
        await client.get(f"{API}/patients/{other_id}", headers=bearer(patient_token))
    ).status_code == 404
    assert (
        await client.patch(
            f"{API}/patients/{other_id}",
            headers=bearer(patient_token),
            json={"full_name": "Hackeo"},
        )
    ).status_code == 404


async def test_paciente_no_puede_desactivarse_a_si_mismo(
    client: AsyncClient, patient_token: str
) -> None:
    patient_id = await _patient_id(client, patient_token)
    response = await client.patch(
        f"{API}/patients/{patient_id}",
        headers=bearer(patient_token),
        json={"is_active": False},
    )
    assert response.status_code == 403


async def test_admin_puede_desactivar_paciente(client: AsyncClient, admin_token: str) -> None:
    created = await client.post(
        f"{API}/patients",
        headers=bearer(admin_token),
        json={"email": unique_email(), "password": "un-password-valido"},
    )
    patient_id = created.json()["id"]

    response = await client.patch(
        f"{API}/patients/{patient_id}",
        headers=bearer(admin_token),
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_patients_sin_token_da_401(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/patients")).status_code == 401


async def test_citas_de_un_paciente(
    client: AsyncClient, patient_token: str, dentist_id: str, admin_token: str
) -> None:
    starts_at, ends_at = future_slot()
    created = await client.post(
        f"{API}/appointments",
        headers=bearer(patient_token),
        json={"dentist_id": dentist_id, "starts_at": starts_at, "ends_at": ends_at},
    )
    assert created.status_code == 201
    patient_id = await _patient_id(client, patient_token)

    #  El propio paciente ve sus citas.
    own = await client.get(
        f"{API}/patients/{patient_id}/appointments", headers=bearer(patient_token)
    )
    assert own.status_code == 200
    assert [item["id"] for item in own.json()] == [created.json()["id"]]

    #  El admin tambien.
    as_admin = await client.get(
        f"{API}/patients/{patient_id}/appointments", headers=bearer(admin_token)
    )
    assert as_admin.status_code == 200
    assert len(as_admin.json()) == 1


async def test_paciente_no_ve_citas_de_otro_paciente(
    client: AsyncClient, patient_token: str, admin_token: str
) -> None:
    other = await client.post(
        f"{API}/patients",
        headers=bearer(admin_token),
        json={"email": unique_email(), "password": "un-password-valido"},
    )
    other_id = other.json()["id"]

    response = await client.get(
        f"{API}/patients/{other_id}/appointments", headers=bearer(patient_token)
    )
    assert response.status_code == 404
