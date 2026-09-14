# Cotizaciones — Hogar de los Alpes

Microservicio de la entrega 4. Consume el comando `SolicitarCotizacion.v1` desde Pulsar, resuelve cada petición contra un catálogo sintético versionado, persiste una cotización PROPUESTA o RECHAZADA en su propia base PostgreSQL y publica un único evento de resultado (`CotizacionRegistrada.v1` o `CotizacionRechazada.v1`) mediante outbox. HTTP solo expone consultas y salud.

Plan de implementación: [docs/plans/README.md](docs/plans/README.md). Evidencias por fase: [docs/evidencias/](docs/evidencias/). Contratos: [docs/contratos/README.md](docs/contratos/README.md).

## Estado

**Fases 01–08 terminadas.** Una instancia es un único proceso FastAPI que:
- consume comandos de Pulsar y hace ACK después del commit;
- resuelve la petición y confirma en una sola transacción la cotización, la marca de inbox y la salida del outbox;
- publica los resultados desde el outbox;
- atiende HTTP: `/health/live`, `/health/ready` y consultas de sus propias cotizaciones.

La integración con Orquestación y Seguimiento reales sigue pendiente: hoy se usa el doble
etiquetado (`enviar_peticion.py`/`consumir_resultados.py`), porque esos dos servicios todavía no
existen como código en el curso.

Desde la Fase 08, el escritor publica el Record v2 de `CotizacionRegistrada.v1`
(`version_contrato = 2`) con el campo opcional `duracion_estimada_minutos` (E3): ver
[docs/evidencias/08-evolucion-e3.md](docs/evidencias/08-evolucion-e3.md) y
[docs/experimentos/e3-cotizaciones.md](docs/experimentos/e3-cotizaciones.md).

## Arquitectura

Un solo módulo Python (`cotizaciones`), arquitectura hexagonal por capas: `dominio` (puro, sin
dependencias de infraestructura), `aplicacion` (casos de uso y puertos), `infraestructura` (SQL,
Avro, Pulsar) y un `seedwork` compartido por capa. Un único proceso por instancia (API HTTP,
consumo de Pulsar y despacho del outbox conviven en los mismos hilos del `lifespan` de FastAPI;
ver «Mensajería» más abajo) — no hay workers ni procesos separados que coordinar.

## Consultas

`GET /cotizaciones/{id_cotizacion}` y `GET /cotizaciones?id_peticion=…&id_trabajo=…&estado=…&limite=…&desplazamiento=…`. Contrato completo: [docs/contratos/consultas.md](docs/contratos/consultas.md) y [openapi.json](docs/contratos/openapi.json).

```bash
curl http://127.0.0.1:8002/cotizaciones/<id_cotizacion>
curl "http://127.0.0.1:8002/cotizaciones?id_peticion=<id_peticion>"
```

Recepción del comando, resultado confirmado en PostgreSQL y publicación a Orquestación son tres momentos distintos: estas consultas solo ven el segundo.

## Recuperación y escalamiento (E8/E4)

- **Métricas y reconciliación:** `scripts/muestrear_metricas.py` (CSV con totales, latencia comando→efecto, pendientes del outbox y backlog/consumidores de Pulsar) y `scripts/reconciliar.py` (compara el JSONL de peticiones enviadas contra la base y produce `reconciliacion.json` con elegibles/propuestas/rechazos/pendientes/duplicadas).
- **Caída y recuperación probadas** (`tests/integracion/test_recuperacion.py`): dos cohortes, la segunda enviada con el servicio detenido; al reabrir con la misma base y suscripción, ambas cohortes quedan reconciliadas sin pendientes ni duplicados.
- **Réplicas concurrentes bajo carga** (`tests/integracion/test_concurrencia.py`): 2 y 4 instancias completas (API + consumo + despacho) sobre la misma suscripción, con 200 comandos mezclando reentregas exactas y peticiones repetidas con otro `command_id`. Ninguna cotización ni salida se duplica.
- **Procedimientos de laboratorio:** [docs/experimentos/e8-cotizaciones.md](docs/experimentos/e8-cotizaciones.md) (Cotizaciones como servicio que falla) y [docs/experimentos/e4-cotizaciones.md](docs/experimentos/e4-cotizaciones.md) (1/2/4 instancias bajo 4× carga). Evidencia: [docs/evidencias/07-recuperacion-y-escala.md](docs/evidencias/07-recuperacion-y-escala.md).

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

El CI (`.github/workflows/ci.yml`) tiene tres jobs en Ubuntu:
- `verificacion-unitaria`: ruff, mypy, pruebas unitarias, de API y de contratos, y distribución;
- `integracion`: `tests/integracion` (salvo compatibilidad de broker) contra PostgreSQL 17.6 (contenedor de servicio) y Pulsar 4.1.3 standalone (`docker run`);
- `compatibilidad`: solo las pruebas de compatibilidad de esquema de E3 (Paso 57) contra un Pulsar standalone recién levantado, con objetivo de duración < 60 s.

## Topología de datos

Cada microservicio del curso tiene su propia base y sus propias credenciales: Cotizaciones nunca
comparte tablas, esquema ni usuario de PostgreSQL con Entrada, Orquestación o Seguimiento. Los
esquemas `cotizaciones` y `mensajeria` (ver «Base de datos») son internos a esta instancia; nada
externo los consulta directamente. La única superficie compartida entre servicios son los tópicos
de Pulsar (ver «Mensajería») y las consultas HTTP de este mismo servicio.

## Imagen y despliegue

- **`Dockerfile`** (Paso 60): construcción en dos etapas sobre `python:3.12.3-slim`; capa de
  dependencias cacheable (`uv sync --no-install-project`) separada de la capa del proyecto;
  usuario no root; arranque con un solo proceso Uvicorn (`cotizaciones.api.app:create_app`) en
  forma `exec`, para que `SIGTERM` llegue directo a Uvicorn y el cierre sea ordenado y menor a
  8 s. `.dockerignore` excluye `.venv`, cachés, `tests`, `docs` y `.git`. En Apple Silicon,
  construir con `--platform linux/amd64` (la plataforma de Cloud Run):

  ```bash
  docker build --platform linux/amd64 -t cotizaciones:v1 .
  ```

- **Laboratorio de imagen** (`docker-compose.imagen.yaml`, Paso 61): stack aislado con su propio
  PostgreSQL y Pulsar (el Pulsar de desarrollo anuncia `127.0.0.1` y no es alcanzable desde otro
  contenedor). Migra, carga y activa el catálogo, prepara Pulsar, arranca el servicio y corre el
  smoke:

  ```bash
  docker compose -f docker-compose.imagen.yaml up --build --abort-on-container-exit
  ```

- **Smoke de despliegue** (`scripts/smoke_despliegue.py`, Paso 62): verifica una imagen ya
  corriendo sin conocer su código fuente — salud, envío de F1/F5 por el doble de Orquestación
  (nunca por HTTP) y confirmación del resultado por `GET /cotizaciones`.
- **Runbook de Cloud Run** (Paso 63): [docs/despliegue/cloud-run.md](docs/despliegue/cloud-run.md)
  — documento, no ejecuta `gcloud`. Prerrequisitos del equipo, parámetros del Service, Jobs
  previos con la misma imagen y verificación posterior.
- Congelación de la imagen v1 y checksums:
  [docs/contratos/CONGELACION-v1.md](docs/contratos/CONGELACION-v1.md).

## Guion de demo

1. Un comando `SolicitarCotizacion.v1` llega por Pulsar (doble de Orquestación).
2. Se resuelve con el catálogo vigente y queda una fila en `cotizaciones.cotizaciones`.
3. El resultado lo leen dos suscripciones distintas del mismo tópico de salida (por ejemplo,
   Orquestación y Seguimiento), cada una con su propio cursor.
4. Una oferta homologada solo se propone si el partner de la petición coincide con el de la
   oferta; una categoría sin oferta produce un rechazo legítimo (`SIN_OFERTA_PARA_CATEGORIA`).
5. Se detiene el servicio con tráfico en curso: Entrada/Orquestación siguen aceptando (el mensaje
   queda en el tópico), el backlog de `cotizaciones-peticiones-v1` crece y, al reiniciar, se
   drena sin duplicar nada (`docs/experimentos/e8-cotizaciones.md`).
6. Un mensaje duplicado (misma `command_id`, reentrega técnica) no genera trabajo nuevo; una
   petición realmente repetida con otro `command_id` para la misma `id_peticion` sí se detecta,
   pero como conflicto de negocio, no como duplicado técnico — la diferencia está en
   `tests/integracion/test_concurrencia.py` y en `ProcesarPeticionHandler`.
7. Duración estimada en E3: se activa `datos/catalogos/catalogo-v2.json` y las peticiones nuevas
   de plomería, cerrajería y electricidad publican 30, 90 y nulo minutos respectivamente; una
   petición ya resuelta con el catálogo v1 conserva su duración nula y no se republica
   (`docs/experimentos/e3-cotizaciones.md`).

## Limitaciones

- Sin Orquestación ni Seguimiento reales, toda integración cruzada usa dobles de laboratorio
  (`scripts/enviar_peticion.py`, `scripts/consumir_resultados.py`); ningún flujo end-to-end real
  entre los cuatro microservicios se ha ejecutado todavía.
- El despliegue en Cloud Run está documentado (`docs/despliegue/cloud-run.md`) pero no ejecutado:
  no existen proyecto, Cloud SQL ni clúster Pulsar del equipo en la fecha de este documento.
- El rollback del escritor v2 de E3 tiene un límite estructural, no solo operativo: un hecho ya
  publicado con `version_contrato = 2` no se puede volver a emitir con el mapeador v1 (detalle en
  [docs/evidencias/08-evolucion-e3.md](docs/evidencias/08-evolucion-e3.md)).
- E4 (escalamiento) y E8 (recuperación) están verificados con réplicas locales reales, pero las
  corridas formales de laboratorio (condiciones cronometradas, λ calibrada) no se han ejecutado
  como experimento grupal; ver los límites propios de cada documento en `docs/experimentos/`.
