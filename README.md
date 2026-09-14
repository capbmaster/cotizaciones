# Cotizaciones — Hogar de los Alpes

Microservicio de la entrega 4. Consume el comando `SolicitarCotizacion.v1` desde Pulsar, resuelve cada petición contra un catálogo sintético versionado, persiste una cotización PROPUESTA o RECHAZADA en su propia base PostgreSQL y publica un único evento de resultado (`CotizacionRegistrada.v1` o `CotizacionRechazada.v1`) mediante outbox. HTTP solo expone consultas y salud.

Plan de implementación: [docs/plans/README.md](docs/plans/README.md). Evidencias por fase: [docs/evidencias/](docs/evidencias/). Contratos: [docs/contratos/README.md](docs/contratos/README.md).

## Estado

**Fases 01–06 terminadas.** Una instancia es un único proceso FastAPI que:
- consume comandos de Pulsar y hace ACK después del commit;
- resuelve la petición y confirma en una sola transacción la cotización, la marca de inbox y la salida del outbox;
- publica los resultados desde el outbox;
- atiende HTTP: `/health/live`, `/health/ready` y consultas de sus propias cotizaciones.

La integración con Orquestación real sigue pendiente: hoy se usa el doble etiquetado.

## Consultas

`GET /cotizaciones/{id_cotizacion}` y `GET /cotizaciones?id_peticion=…&id_trabajo=…&estado=…&limite=…&desplazamiento=…`. Contrato completo: [docs/contratos/consultas.md](docs/contratos/consultas.md) y [openapi.json](docs/contratos/openapi.json).

```bash
curl http://127.0.0.1:8002/cotizaciones/<id_cotizacion>
curl "http://127.0.0.1:8002/cotizaciones?id_peticion=<id_peticion>"
```

Recepción del comando, resultado confirmado en PostgreSQL y publicación a Orquestación son tres momentos distintos: estas consultas solo ven el segundo.

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

## Mensajería

| Tópico | Contrato | Rol | Suscripción del servicio |
|---|---|---|---|
| `solicitar-cotizacion-v1` | `SolicitarCotizacion.v1` (propietario: Orquestación; aquí, propuesta lectora) | Consumidor Shared | `cotizaciones-peticiones-v1` |
| `cotizacion-registrada-v1` | `CotizacionRegistrada.v1` | Productor | — |
| `cotizacion-rechazada-v1` | `CotizacionRechazada.v1` | Productor | — |

Esquemas, ejemplos, checksums y reglas: [docs/contratos/](docs/contratos/README.md).

Preparar esquemas y suscripciones antes del tráfico. Opcionalmente, aplicar cuota de backlog y retención:

```bash
docker compose exec dev uv run --locked python scripts/preparar_pulsar.py --admin-url http://pulsar:8080
```

Recorrido local con los dobles (**DOBLE DE ORQUESTACION** y **DOBLE LECTOR v1**; no son servicios reales). El servicio escucha dentro de la red de Compose y usa `pulsar://pulsar:6650`:

```bash
docker compose exec -e COTIZACIONES_DATABASE_URL=postgresql+psycopg://cotizaciones:cotizaciones_local@postgres:5432/cotizaciones -e COTIZACIONES_PULSAR_URL=pulsar://pulsar:6650 dev uv run --locked uvicorn cotizaciones.api.app:create_app --factory --host 0.0.0.0 --port 8002
```

En otra terminal, enviar una petición con el doble de Orquestación:

```bash
docker compose exec -e COTIZACIONES_PULSAR_URL=pulsar://pulsar:6650 dev uv run --locked python scripts/enviar_peticion.py --categoria plomeria
```

Leer el resultado con el doble lector v1:

```bash
docker compose exec -e COTIZACIONES_PULSAR_URL=pulsar://pulsar:6650 dev uv run --locked python scripts/consumir_resultados.py --solo registrada --suscripcion orquestacion-cotizacion-registrada-v1 --base /tmp/orquestacion.db
```

**Ciclo de vida** (un solo proceso por instancia):
- El `lifespan` de FastAPI inicia dos hilos: `consumo-peticiones` y `despacho-resultados`.
- **Consumo:** ACK solo después del commit.
  - Error técnico (base caída, catálogo ausente) → NACK y reintento.
  - Mensaje inválido o contradictorio → sin ACK ni NACK; el consumo se pausa y `/health/ready` informa el ID y el motivo.
- **Despacho:** publica desde el outbox con reservas.
- **Al cerrar:** detiene ambos hilos en menos de 10 s, sin ACK ni marcas del outbox y sin anular suscripciones.

## Arranque sin base (solo salud)

```bash
docker compose exec dev uv run --locked uvicorn cotizaciones.api.app:create_app --factory --host 0.0.0.0 --port 8002
```

Sin `COTIZACIONES_DATABASE_URL`, `/health/ready` responde 503 con `base_no_configurada` y no se inicia la mensajería. En Cloud Run el puerto lo inyecta `PORT`.

## Configuración

Variables con prefijo `COTIZACIONES_`, descritas en [docs/plans/00-contratos-y-datos.md §11](docs/plans/00-contratos-y-datos.md). [.env.example](.env.example) lista todas con los valores del entorno Docker.

## Verificación estándar

Desde la raíz, dentro de `dev` (anteponer `docker compose exec dev`). `tests/integracion` necesita PostgreSQL y Pulsar arriba:
- crea y borra una base temporal `cotizaciones_test_<uuid>`;
- usa tópicos únicos por prueba, que borra al terminar.

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
- `integracion`: `tests/integracion` contra PostgreSQL 17.6 (contenedor de servicio) y Pulsar 4.1.3 standalone (`docker run`).
