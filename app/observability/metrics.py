"""Metricas Prometheus.

Middleware ASGI puro (no `BaseHTTPMiddleware`): este ultimo envuelve cada
request en un task group de anyio, lo que agrega overhead y ruido justo en lo
que se quiere medir.

Cardinalidad: la etiqueta `route` usa el PATRON de la ruta
(`/api/v1/appointments/{appointment_id}`) y nunca la URL concreta. Con la URL
literal, cada UUID de una corrida de carga crearia una serie nueva y el
endpoint /metrics terminaria inutilizable.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNMATCHED_ROUTE = "__unmatched__"

REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Requests HTTP atendidos.",
    ["method", "route", "status"],
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Duracion del request medida por el servidor.",
    ["method", "route"],
    #  Buckets pensados para una API web: desde 5 ms hasta 10 s.
    buckets=(
        0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5,
        0.75, 1.0, 2.5, 5.0, 10.0,
    ),
)

REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Requests en vuelo en este momento.",
    ["method"],
)

CHAOS_INJECTED_TOTAL = Counter(
    "chaos_injected_total",
    "Fallas inyectadas por el modulo de caos.",
    ["kind"],
)


def metrics_payload() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


class MetricsMiddleware:
    """Contabiliza cada request HTTP.

    Va como middleware MAS EXTERNO, de modo que la latencia registrada incluye
    la que inyecta el caos: es lo que observa el cliente.
    """

    def __init__(self, app: ASGIApp, router: Any = None, exempt_paths: frozenset[str] | None = None):
        self.app = app
        self.router = router
        self.exempt_paths = exempt_paths if exempt_paths is not None else frozenset({"/metrics"})
        #  endpoint (funcion) -> patron de ruta. Resolver el patron recorriendo
        #  las rutas en cada request costaria un regex por request; con este
        #  cache es O(1) y queda acotado por la cantidad de rutas.
        self._route_cache: dict[Any, str] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        REQUESTS_IN_PROGRESS.labels(method).inc()
        started = perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = perf_counter() - started
            route = self._route_label(scope)
            REQUESTS_IN_PROGRESS.labels(method).dec()
            REQUEST_DURATION.labels(method, route).observe(elapsed)
            REQUESTS_TOTAL.labels(method, route, str(status_code)).inc()

    def _route_label(self, scope: Scope) -> str:
        #  Starlette deja el objeto de ruta y/o el endpoint en el scope una vez
        #  resuelto el ruteo, es decir, ya de vuelta en este middleware.
        route = scope.get("route")
        path = getattr(route, "path", None)
        if path:
            return path

        endpoint = scope.get("endpoint")
        if endpoint is not None:
            cached = self._route_cache.get(endpoint)
            if cached is not None:
                return cached
            if self.router is not None:
                for candidate in self.router.routes:
                    if getattr(candidate, "endpoint", None) is endpoint:
                        resolved = getattr(candidate, "path", UNMATCHED_ROUTE)
                        self._route_cache[endpoint] = resolved
                        return resolved

        #  Nadie llego a rutear: pasa cuando el caos corta el request antes del
        #  router. Sin esto, TODOS los errores inyectados caerian en la misma
        #  serie y no se sabria que endpoint golpearon. Solo se paga este loop
        #  en ese caso y en los 404.
        return self._match_pattern(scope)

    def _match_pattern(self, scope: Scope) -> str:
        if self.router is None:
            return UNMATCHED_ROUTE

        partial: str | None = None
        for candidate in self.router.routes:
            try:
                match, _ = candidate.matches(scope)
            except Exception:  # pragma: no cover - ruta exotica sin matches()
                continue
            if match is Match.FULL:
                return getattr(candidate, "path", UNMATCHED_ROUTE)
            #  PARTIAL = el path calza pero el metodo no (405).
            if match is Match.PARTIAL and partial is None:
                partial = getattr(candidate, "path", None)

        #  404 reales: etiqueta fija para no abrir una serie por URL.
        return partial or UNMATCHED_ROUTE
