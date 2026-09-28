"""Estado del caos: vive en memoria del proceso y se cambia en caliente."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings


class ChaosState(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enabled": True,
                "latency_ms": 200,
                "latency_jitter_ms": 50,
                "error_rate": 0.05,
                "error_status": 503,
                "routes": ["/api/v1/appointments*"],
            }
        }
    )

    enabled: bool = Field(default=False, description="Interruptor general.")
    latency_ms: int = Field(default=0, ge=0, le=60_000, description="Retardo base en ms.")
    latency_jitter_ms: int = Field(
        default=0, ge=0, le=60_000, description="Variacion uniforme +/- sobre el retardo base."
    )
    error_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Probabilidad de cortar el request con error."
    )
    error_status: int = Field(default=503, ge=400, le=599, description="Status del error inyectado.")
    routes: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Patrones glob sobre el path. '*' afecta a todo lo no exento.",
    )


class ChaosUpdate(BaseModel):
    """Igual que ChaosState pero con todos los campos opcionales (PATCH-like).

    Un PUT con solo {"error_rate": 0.1} deja el resto como estaba.
    """

    enabled: bool | None = None
    latency_ms: int | None = Field(default=None, ge=0, le=60_000)
    latency_jitter_ms: int | None = Field(default=None, ge=0, le=60_000)
    error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    error_status: int | None = Field(default=None, ge=400, le=599)
    routes: list[str] | None = None


def state_from_settings() -> ChaosState:
    return ChaosState(
        enabled=settings.chaos_enabled,
        latency_ms=settings.chaos_latency_ms,
        latency_jitter_ms=settings.chaos_latency_jitter_ms,
        error_rate=settings.chaos_error_rate,
        error_status=settings.chaos_error_status,
        routes=settings.chaos_route_patterns,
    )


#  Se reemplaza entero en cada cambio en vez de mutar campos: la asignacion a
#  la global es atomica, asi que un request que ya tomo la referencia trabaja
#  con una foto coherente y no hace falta ningun lock.
_state: ChaosState = state_from_settings()


def get_chaos_state() -> ChaosState:
    return _state


def set_chaos_state(update: ChaosUpdate) -> ChaosState:
    global _state
    _state = _state.model_copy(update=update.model_dump(exclude_none=True))
    return _state


def reset_chaos_state() -> ChaosState:
    """Vuelve a los valores de las variables de entorno."""
    global _state
    _state = state_from_settings()
    return _state
