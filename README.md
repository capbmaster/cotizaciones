# Cotizaciones — Hogar de los Alpes

Microservicio de la entrega 4. Consume el comando `SolicitarCotizacion.v1` desde Pulsar, resuelve cada petición contra un catálogo sintético versionado, persiste una cotización PROPUESTA o RECHAZADA en su propia base PostgreSQL y publica un único evento de resultado (`CotizacionRegistrada.v1` o `CotizacionRechazada.v1`) mediante outbox. HTTP solo expone consultas y salud.

Plan de implementación: [docs/plans/README.md](docs/plans/README.md). Evidencias por fase: [docs/evidencias/](docs/evidencias/).

## Estado

**Fases 01–04 terminadas**:
- Dominio y caso de uso idempotente.
- Persistencia en PostgreSQL: cotización, marca de inbox y salida de outbox se confirman atómicamente; hay reservas del outbox y un catálogo versionado cargable.

Todavía **no** hay consumo de Pulsar ni publicación de resultados: llegan en la fase 05. Las salidas quedan pendientes en `mensajeria.outbox`.

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

## Base de datos

Esquemas `cotizaciones` (catálogos, ofertas, cotizaciones) y `mensajeria` (inbox, outbox, archivo de eventos). Migraciones con Alembic, que se aplican como paso previo y nunca al arrancar el servicio.

Todos los comandos siguientes se ejecutan desde `dev`, con `COTIZACIONES_DATABASE_URL=postgresql+psycopg://cotizaciones:cotizaciones_local@postgres:5432/cotizaciones`:

```bash
docker compose exec -e COTIZACIONES_DATABASE_URL=postgresql+psycopg://cotizaciones:cotizaciones_local@postgres:5432/cotizaciones dev uv run --locked alembic upgrade head
```

Cargar y activar el catálogo sintético v1 (idempotente; termina con código 2 si esa versión ya existe con otro contenido):

```bash
docker compose exec -e COTIZACIONES_DATABASE_URL=postgresql+psycopg://cotizaciones:cotizaciones_local@postgres:5432/cotizaciones dev uv run --locked python scripts/cargar_catalogo.py --activar
```

Ver las salidas pendientes del outbox:

```bash
docker compose exec -e COTIZACIONES_DATABASE_URL=postgresql+psycopg://cotizaciones:cotizaciones_local@postgres:5432/cotizaciones dev uv run --locked python scripts/inspeccionar_outbox.py
```

Las conexiones fijan `search_path=public`. El usuario de la base se llama igual que el esquema `cotizaciones`, y con el `search_path` por defecto (`"$user", public`) ese esquema pasaría a ser el esquema por defecto.

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

Desde la raíz, dentro de `dev` (anteponer `docker compose exec dev`). Las pruebas de `tests/integracion` necesitan PostgreSQL arriba; crean y borran una base temporal `cotizaciones_test_<uuid>`:

```bash
uv sync --locked
uv run --locked pytest tests -q -s --tb=short
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src tests scripts migraciones
uv run --locked python scripts/verify_distribution.py
```

Y en el host: `git diff --check`.

El CI (`.github/workflows/ci.yml`) tiene dos jobs en Ubuntu:
- `verificacion-unitaria`: ruff, mypy, pruebas unitarias, de API y de contratos, y distribución;
- `integracion-postgres`: `tests/integracion` contra un PostgreSQL 17.6 de servicio.
