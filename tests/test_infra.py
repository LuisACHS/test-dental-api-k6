from __future__ import annotations

from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import bearer

API = settings.api_v1_prefix


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_openapi_y_swagger(client: AsyncClient) -> None:
    schema = await client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert f"{API}/auth/login" in paths
    assert f"{API}/appointments" in paths

    assert (await client.get("/docs")).status_code == 200


async def test_metrics_usa_el_patron_de_ruta(
    client: AsyncClient, patient_token: str, dentist_id: str
) -> None:
    """La etiqueta `route` debe ser el patron, nunca la URL con el UUID.

    Con la URL literal cada id de una corrida de carga abriria una serie nueva.
    """
    await client.get(f"{API}/dentists/{dentist_id}", headers=bearer(patient_token))

    body = (await client.get("/metrics")).text
    assert 'route="/api/v1/dentists/{dentist_id}"' in body
    assert dentist_id not in body
    assert "http_request_duration_seconds_bucket" in body
    assert "http_requests_in_progress" in body
