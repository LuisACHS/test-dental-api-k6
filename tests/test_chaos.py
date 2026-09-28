from __future__ import annotations

from collections.abc import AsyncIterator
from time import perf_counter

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import bearer

API = settings.api_v1_prefix
ADMIN = {"X-Admin-Token": settings.admin_token}


@pytest.fixture
async def chaos_reset(client: AsyncClient) -> AsyncIterator[None]:
    """Deja el caos como estaba pase lo que pase en el test."""
    try:
        yield
    finally:
        #  Estado limpio explicito y no /reset: en la instancia con caos el
        #  reset vuelve a CHAOS_ENABLED=true y contaminaria los tests que siguen.
        await client.put(
            "/admin/chaos",
            headers=ADMIN,
            json={"enabled": False, "latency_ms": 0, "latency_jitter_ms": 0,
                  "error_rate": 0.0, "error_status": 503, "routes": ["*"]},
        )


async def test_admin_chaos_requiere_token(client: AsyncClient) -> None:
    assert (await client.get("/admin/chaos")).status_code == 401
    assert (
        await client.get("/admin/chaos", headers={"X-Admin-Token": "equivocado"})
    ).status_code == 401
    assert (await client.get("/admin/chaos", headers=ADMIN)).status_code == 200


async def test_put_parcial_no_pisa_el_resto(client: AsyncClient, chaos_reset: None) -> None:
    await client.put(
        "/admin/chaos", headers=ADMIN, json={"enabled": True, "latency_ms": 123, "error_status": 429}
    )
    response = await client.put("/admin/chaos", headers=ADMIN, json={"error_rate": 0.5})
    assert response.status_code == 200

    state = response.json()
    assert state["error_rate"] == 0.5
    assert state["latency_ms"] == 123
    assert state["error_status"] == 429


async def test_error_inyectado(client: AsyncClient, patient_token: str, chaos_reset: None) -> None:
    await client.put(
        "/admin/chaos",
        headers=ADMIN,
        json={"enabled": True, "error_rate": 1.0, "error_status": 503, "routes": ["/api/v1/*"]},
    )

    response = await client.get(f"{API}/dentists", headers=bearer(patient_token))
    assert response.status_code == 503
    assert response.headers.get("X-Chaos-Injected") == "error"
    assert response.json()["chaos"] is True

    #  Apagarlo restaura el comportamiento normal.
    await client.put("/admin/chaos", headers=ADMIN, json={"enabled": False})
    assert (await client.get(f"{API}/dentists", headers=bearer(patient_token))).status_code == 200


async def test_rutas_de_control_quedan_exentas(
    client: AsyncClient, chaos_reset: None
) -> None:
    """Con error_rate=1.0 sobre '*', /admin y /metrics tienen que seguir vivos.

    Si no, no habria forma de apagar el caos sin reiniciar el contenedor.
    """
    await client.put(
        "/admin/chaos", headers=ADMIN, json={"enabled": True, "error_rate": 1.0, "routes": ["*"]}
    )

    assert (await client.get("/admin/chaos", headers=ADMIN)).status_code == 200
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/metrics")).status_code == 200


async def test_latencia_inyectada(client: AsyncClient, chaos_reset: None) -> None:
    await client.put(
        "/admin/chaos",
        headers=ADMIN,
        json={"enabled": True, "latency_ms": 300, "error_rate": 0.0, "routes": ["/api/v1/*"]},
    )

    started = perf_counter()
    #  Sin token: lo que importa es que el retardo se aplica antes de la ruta.
    await client.get(f"{API}/dentists")
    elapsed = perf_counter() - started
    assert elapsed >= 0.25, f"se esperaba ~300 ms de retardo, hubo {elapsed * 1000:.0f} ms"


async def test_ruta_fuera_del_patron_no_se_afecta(
    client: AsyncClient, patient_token: str, chaos_reset: None
) -> None:
    await client.put(
        "/admin/chaos",
        headers=ADMIN,
        json={"enabled": True, "error_rate": 1.0, "routes": ["/api/v1/appointments*"]},
    )

    #  Fuera del patron: sigue normal.
    assert (await client.get(f"{API}/dentists", headers=bearer(patient_token))).status_code == 200
    #  Dentro del patron: cae.
    assert (
        await client.get(f"{API}/appointments", headers=bearer(patient_token))
    ).status_code == 503


async def test_error_inyectado_se_atribuye_a_su_ruta(
    client: AsyncClient, chaos_reset: None
) -> None:
    """El caos corta antes del router, pero la metrica igual debe decir cual ruta.

    Si no, todos los errores inyectados caen en la misma serie y la corrida no
    sirve para saber que endpoint se degrado.
    """
    await client.put(
        "/admin/chaos",
        headers=ADMIN,
        json={"enabled": True, "error_rate": 1.0, "error_status": 503,
              "routes": ["/api/v1/appointments*"]},
    )
    assert (await client.get(f"{API}/appointments")).status_code == 503

    body = (await client.get("/metrics")).text
    assert 'route="/api/v1/appointments",status="503"' in body
    assert 'chaos_injected_total{kind="error"}' in body


async def test_reset_vuelve_a_las_variables_de_entorno(
    client: AsyncClient, chaos_reset: None
) -> None:
    await client.put("/admin/chaos", headers=ADMIN, json={"enabled": True, "latency_ms": 999})

    response = await client.post("/admin/chaos/reset", headers=ADMIN)
    assert response.status_code == 200

    estado = response.json()
    assert estado["enabled"] is settings.chaos_enabled
    assert estado["latency_ms"] == settings.chaos_latency_ms
    assert estado["error_rate"] == settings.chaos_error_rate
