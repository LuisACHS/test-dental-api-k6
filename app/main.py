from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import __version__
from app.api.admin import router as admin_router
from app.api.v1.router import api_router
from app.chaos.middleware import ChaosMiddleware
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal, engine
from app.models.user import User, UserRole
from app.observability.metrics import MetricsMiddleware, metrics_payload

logger = logging.getLogger("app")

DESCRIPTION = """
API de agendamiento de horas dentales.

**Como usar Swagger:** registrar un usuario en `POST /api/v1/auth/register`,
apretar **Authorize** arriba a la derecha y entrar con ese email y password.

**Banco de pruebas:** `GET /metrics` expone metricas Prometheus y
`PUT /admin/chaos` inyecta latencia y errores en caliente (header
`X-Admin-Token`).
"""


async def _bootstrap_admin() -> None:
    """Crea el admin inicial si esta configurado y no existe. Idempotente."""
    email = settings.bootstrap_admin_email
    password = settings.bootstrap_admin_password
    if not email or not password:
        return

    email = email.strip().lower()
    async with AsyncSessionLocal() as db:
        if await db.scalar(select(User).where(User.email == email)) is not None:
            return
        db.add(
            User(
                email=email,
                hashed_password=hash_password(password),
                full_name="Administrador",
                role=UserRole.admin,
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            #  Otro worker lo creo primero.
            await db.rollback()
            return
    logger.info("admin inicial creado: %s", email)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await _bootstrap_admin()
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(admin_router)

    @app.get("/health", tags=["infra"], summary="Liveness")
    async def health() -> dict[str, str]:
        #  A proposito no toca la base: es el healthcheck del contenedor.
        return {"status": "ok"}

    if settings.metrics_enabled:

        @app.get("/metrics", tags=["infra"], summary="Metricas Prometheus")
        async def metrics() -> Response:
            payload, content_type = metrics_payload()
            return Response(content=payload, media_type=content_type)

    # --- caos: estas dos lineas son todo el enganche -----------------------
    app.add_middleware(ChaosMiddleware)
    # --- fin caos ----------------------------------------------------------

    #  Se agrega DESPUES del caos, y en Starlette el ultimo agregado queda por
    #  fuera: asi la latencia medida incluye la inyectada, que es lo que ve el
    #  cliente.
    if settings.metrics_enabled:
        app.add_middleware(MetricsMiddleware, router=app.router)

    return app


app = create_app()
