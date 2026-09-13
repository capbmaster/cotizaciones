# Cotizaciones — Hogar de los Alpes

Microservicio de la entrega 4. Consume el comando `SolicitarCotizacion.v1` desde Pulsar, resuelve cada petición contra un catálogo sintético versionado, persiste una cotización PROPUESTA o RECHAZADA en su propia base PostgreSQL y publica un único evento de resultado (`CotizacionRegistrada.v1` o `CotizacionRechazada.v1`) mediante outbox. HTTP solo expone consultas y salud.

Plan de implementación: [docs/plans/README.md](docs/plans/README.md). Evidencias por fase: [docs/evidencias/](docs/evidencias/).

## Estado

**Fase 01 terminada** (entorno y base tecnológica). La app FastAPI arranca con lifespan y expone `/health/live` y `/health/ready`. Todavía **no** hay procesamiento durable, consumo de Pulsar ni publicación de resultados: llegan en las fases 04 y 05.

## Entorno de desarrollo (Docker)

No se instala nada en el host. `docker-compose.yaml` levanta tres servicios:

| Servicio | Imagen | Uso |
|---|---|---|
| `postgres` | `postgres:17.6` | Base propia, publicada en `127.0.0.1:55436` |
| `pulsar` | `apachepulsar/pulsar:4.1.3` | Broker standalone de desarrollo; admin en `127.0.0.1:18096` |
| `dev` | `python:3.12.3-slim` + uv 0.10.9 | uv, pytest, ruff, mypy, alembic y scripts, con el repositorio en `/app` |

```bash
docker compose up -d --build --wait
```

Instalar dependencias (el entorno vive en el volumen `/opt/venv` del contenedor):

```bash
docker compose exec dev uv sync --locked
```

Los hosts `postgres` y `pulsar` solo existen dentro de la red de Compose. El puerto binario de Pulsar no se publica al host.

## Arranque

Dentro del contenedor, sin base de datos (solo salud):

```bash
docker compose exec dev uv run --locked uvicorn cotizaciones.api.app:create_app --factory --host 0.0.0.0 --port 8002
```

Desde el host:

```bash
curl http://127.0.0.1:8002/health/live
```

Sin `COTIZACIONES_DATABASE_URL`, `/health/ready` responde 503 con `base_no_configurada`. En Cloud Run el puerto lo inyecta `PORT`.

## Configuración

Variables con prefijo `COTIZACIONES_`, descritas en [docs/plans/00-contratos-y-datos.md §11](docs/plans/00-contratos-y-datos.md). [.env.example](.env.example) lista todas con los valores del entorno Docker.

## Verificación estándar

Desde la raíz, dentro de `dev` (anteponer `docker compose exec dev`):

```bash
uv sync --locked
uv run --locked pytest tests -q -s --tb=short
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src tests scripts
uv run --locked python scripts/verify_distribution.py
```

Y en el host: `git diff --check`. `mypy` incluirá `migraciones` cuando exista (fase 04).

El CI (`.github/workflows/ci.yml`) ejecuta el job `verificacion-unitaria` en Ubuntu con las mismas herramientas sobre `tests/unitarias`, `tests/api` y `tests/contratos`.
