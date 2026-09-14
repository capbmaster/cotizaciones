# syntax=docker/dockerfile:1
# Construir para linux/amd64 (plataforma de Cloud Run), incluso en Apple Silicon:
#   docker build --platform linux/amd64 -t cotizaciones:v1 .

FROM ghcr.io/astral-sh/uv:0.10.9 AS uv

# --- Etapa 1: dependencias (capa cacheable, sin el codigo propio) ---
FROM python:3.12.3-slim AS build
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_EDITABLE=1
WORKDIR /app

COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY alembic.ini ./alembic.ini
COPY migraciones ./migraciones
COPY scripts ./scripts
COPY datos ./datos
RUN uv sync --locked --no-dev

# --- Etapa 2: imagen final, solo el entorno virtual y lo necesario para correr ---
FROM python:3.12.3-slim AS final
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system cotizaciones && \
    useradd --system --gid cotizaciones --home-dir /app --no-create-home cotizaciones

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --from=build /app/alembic.ini ./alembic.ini
COPY --from=build /app/migraciones ./migraciones
COPY --from=build /app/scripts ./scripts
COPY --from=build /app/datos ./datos

USER cotizaciones
EXPOSE 8002

# Forma exec (sin shell) para que uvicorn reciba SIGTERM directamente y cierre en <8s.
# PORT lo inyecta Cloud Run (por defecto 8002 en local, ver docker-compose.imagen.yaml).
ENV PORT=8002
CMD ["sh", "-c", "exec uvicorn cotizaciones.api.app:create_app --factory --host 0.0.0.0 --port ${PORT}"]
