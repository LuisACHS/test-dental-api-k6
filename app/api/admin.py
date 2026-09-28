"""Control en caliente del caos.

Fuera de /api/v1 a proposito: no es parte del contrato de la API de negocio,
es la perilla del banco de pruebas. Protegido con el token estatico
ADMIN_TOKEN para que un harness externo lo maneje con un curl.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.chaos import ChaosState, ChaosUpdate, get_chaos_state, reset_chaos_state, set_chaos_state
from app.core.deps import require_admin_token

router = APIRouter(
    prefix="/admin",
    tags=["admin (caos)"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/chaos", response_model=ChaosState, summary="Ver el caos vigente")
async def read_chaos() -> ChaosState:
    return get_chaos_state()


@router.put(
    "/chaos",
    response_model=ChaosState,
    summary="Modificar el caos en caliente",
    description=(
        "Solo se aplican los campos enviados; el resto queda como estaba.\n\n"
        "```bash\n"
        "curl -X PUT localhost:8000/admin/chaos \\\n"
        '  -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \\\n'
        '  -d \'{"enabled":true,"latency_ms":200,"latency_jitter_ms":50,"error_rate":0.05}\'\n'
        "```\n\n"
        "El estado vive en memoria del proceso: con `WORKERS>1` cada worker "
        "tiene el suyo."
    ),
)
async def update_chaos(payload: ChaosUpdate) -> ChaosState:
    return set_chaos_state(payload)


@router.post(
    "/chaos/reset",
    response_model=ChaosState,
    summary="Volver a los valores de las variables de entorno",
)
async def reset_chaos() -> ChaosState:
    return reset_chaos_state()
