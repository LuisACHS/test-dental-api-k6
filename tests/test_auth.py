from __future__ import annotations

from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import bearer, unique_email

API = settings.api_v1_prefix


async def test_register_login_me(client: AsyncClient) -> None:
    email = unique_email()
    password = "un-password-valido"

    created = await client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password, "full_name": "Juan Perez"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "patient"
    assert "hashed_password" not in created.json()

    logged = await client.post(
        f"{API}/auth/login", data={"username": email, "password": password}
    )
    assert logged.status_code == 200, logged.text
    token = logged.json()["access_token"]
    assert logged.json()["token_type"] == "bearer"

    me = await client.get(f"{API}/auth/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["email"] == email


async def test_register_duplicado_da_409(client: AsyncClient) -> None:
    email = unique_email()
    payload = {"email": email, "password": "un-password-valido"}
    assert (await client.post(f"{API}/auth/register", json=payload)).status_code == 201
    assert (await client.post(f"{API}/auth/register", json=payload)).status_code == 409


async def test_login_con_password_incorrecta_da_401(client: AsyncClient) -> None:
    email = unique_email()
    await client.post(f"{API}/auth/register", json={"email": email, "password": "correcta-12345"})

    response = await client.post(
        f"{API}/auth/login", data={"username": email, "password": "incorrecta-12345"}
    )
    assert response.status_code == 401


async def test_me_sin_token_da_401(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/auth/me")).status_code == 401


async def test_me_con_token_basura_da_401(client: AsyncClient) -> None:
    response = await client.get(f"{API}/auth/me", headers=bearer("no-es-un-jwt"))
    assert response.status_code == 401
