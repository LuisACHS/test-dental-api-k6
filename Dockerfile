FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/app

# Capa de dependencias aparte del codigo: cambiar una linea de la app no
# reinstala todo.
COPY requirements*.txt ./
# Si existe el lock congelado se usa ese (build reproducible); si no, los
# rangos de requirements.txt. Ver README -> "Congelar el lock".
RUN if [ -f requirements.lock.txt ]; then \
        pip install -r requirements.lock.txt; \
    else \
        pip install -r requirements-dev.txt; \
    fi

COPY . .

RUN chmod +x /srv/app/entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /srv/app

USER appuser

EXPOSE 8000

# Se invoca via sh para no depender del bit de ejecucion al copiar desde Windows.
ENTRYPOINT ["/bin/sh", "/srv/app/entrypoint.sh"]
