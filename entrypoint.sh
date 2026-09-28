#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "[entrypoint] aplicando migraciones..."
    alembic upgrade head
else
    # La segunda instancia (la del caos) arranca despues de la primera y
    # comparte su base: dos alembic concurrentes sobre el mismo esquema chocan.
    echo "[entrypoint] RUN_MIGRATIONS=false, se omiten las migraciones"
fi

UVICORN_ARGS="--host 0.0.0.0 --port 8000 --log-level ${LOG_LEVEL:-info}"

if [ "${ACCESS_LOG:-true}" != "true" ]; then
    # El access log cuesta throughput; se apaga al medir.
    UVICORN_ARGS="$UVICORN_ARGS --no-access-log"
fi

if [ "${RELOAD:-false}" = "true" ]; then
    echo "[entrypoint] modo desarrollo (reload activo, NO usar para medir)"
    exec uvicorn app.main:app $UVICORN_ARGS --reload
fi

echo "[entrypoint] arrancando con ${WORKERS:-1} worker(s)"
exec uvicorn app.main:app $UVICORN_ARGS --workers "${WORKERS:-1}"
