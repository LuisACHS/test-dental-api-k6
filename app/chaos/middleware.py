"""Middleware que inyecta latencia y errores."""

from __future__ import annotations

import asyncio
import random
from fnmatch import fnmatchcase

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.chaos.state import get_chaos_state
from app.observability.metrics import CHAOS_INJECTED_TOTAL

#  Rutas siempre exentas. La mas importante es /admin: si el caos pudiera
#  afectar a /admin/chaos, un error_rate de 1.0 dejaria la API imposible de
#  recuperar sin reiniciar el contenedor.
DEFAULT_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/admin",
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
)


class ChaosMiddleware:
    def __init__(self, app: ASGIApp, exempt_prefixes: tuple[str, ...] | None = None):
        self.app = app
        self.exempt_prefixes = (
            exempt_prefixes if exempt_prefixes is not None else DEFAULT_EXEMPT_PREFIXES
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        #  Una referencia, una foto coherente durante todo el request.
        state = get_chaos_state()

        #  Con el caos apagado el costo es este unico `if`: no contamina la
        #  linea base de la medicion.
        if not state.enabled:
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if self._is_exempt(path) or not self._matches(path, state.routes):
            await self.app(scope, receive, send)
            return

        delay_ms = self._delay_ms(state.latency_ms, state.latency_jitter_ms)
        if delay_ms > 0:
            #  asyncio.sleep y nunca time.sleep: este ultimo congelaria el
            #  event loop completo y se estaria midiendo otra cosa.
            await asyncio.sleep(delay_ms / 1000.0)
            CHAOS_INJECTED_TOTAL.labels("latency").inc()

        if state.error_rate > 0.0 and random.random() < state.error_rate:
            CHAOS_INJECTED_TOTAL.labels("error").inc()
            response = JSONResponse(
                status_code=state.error_status,
                content={"detail": "chaos: error inyectado", "chaos": True},
                headers={"X-Chaos-Injected": "error"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _is_exempt(self, path: str) -> bool:
        return path.startswith(self.exempt_prefixes)

    @staticmethod
    def _matches(path: str, patterns: list[str]) -> bool:
        return any(fnmatchcase(path, pattern) for pattern in patterns)

    @staticmethod
    def _delay_ms(base: int, jitter: int) -> float:
        if base <= 0 and jitter <= 0:
            return 0.0
        if jitter <= 0:
            return float(base)
        return max(0.0, base + random.uniform(-jitter, jitter))
