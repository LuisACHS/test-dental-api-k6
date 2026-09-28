"""Fixtures de las pruebas smoke.

Estas pruebas corren contra la base real del compose (no hay base de pruebas
aparte): cada test crea sus propios datos con identificadores unicos, asi que
son repetibles aunque la base quede sucia entre corridas.

    docker compose exec api pytest -q
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.chaos import ChaosUpdate, set_chaos_state
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, engine
from app.main import app
from app.models.dentist import Dentist
from app.models.user import User, UserRole


@pytest.fixture(scope="session", autouse=True)
def _chaos_off() -> None:
    """Las pruebas asumen una API sin caos.

    El contenedor dental-api-chaos arranca con CHAOS_ENABLED=true; sin esto la
    suite corrida ahi fallaria con 503 aleatorios en cualquier fixture.
    """
    set_chaos_state(ChaosUpdate(enabled=False))


@pytest.fixture(scope="session", autouse=True)
async def _dispose_engine():
    """Cierra el pool antes de que se cierre el event loop de la sesion."""
    yield
    await engine.dispose()


def unique_email(prefix: str = "test") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@dental.local"


def future_slot(minutes: int = 30, days_ahead: int = 30) -> tuple[str, str]:
    """Rango horario a futuro, en ISO 8601 con zona horaria."""
    start = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).replace(
        minute=0, second=0, microsecond=0
    )
    return start.isoformat(), (start + timedelta(minutes=minutes)).isoformat()


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture
def api(request) -> str:
    return settings.api_v1_prefix


@pytest.fixture
async def dentist_id() -> str:
    """Un dentista nuevo por test: evita choques de horario entre pruebas."""
    async with AsyncSessionLocal() as db:
        dentist = Dentist(full_name=f"Dr. Test {uuid.uuid4().hex[:6]}", specialty="General")
        db.add(dentist)
        await db.commit()
        await db.refresh(dentist)
        return str(dentist.id)


@pytest.fixture
async def admin_token(client: AsyncClient) -> str:
    """Crea un admin directo en la base y devuelve su access token."""
    email = unique_email("admin")
    password = "admin-test-12345"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                hashed_password=hash_password(password),
                full_name="Admin de prueba",
                role=UserRole.admin,
            )
        )
        await db.commit()

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
async def patient_token(client: AsyncClient) -> str:
    email = unique_email("patient")
    password = "patient-test-12345"
    response = await client.post(
        f"{settings.api_v1_prefix}/auth/register",
        json={"email": email, "password": password, "full_name": "Paciente de prueba"},
    )
    assert response.status_code == 201, response.text

    response = await client.post(
        f"{settings.api_v1_prefix}/auth/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
