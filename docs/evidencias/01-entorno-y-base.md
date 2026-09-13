# Evidencia 01 — Entorno y base tecnológica

Estado: **Fase 01 terminada** (Pasos 1–9). Fecha: 2026-09-13 (Bogotá).

## Paso 1 — Herramientas locales

Decisión del usuario: trabajar con Docker y no instalar herramientas en el host. El usuario descargó las imágenes y levantó `docker-compose.yaml` (`docker compose up -d --build --wait`).

| Elemento | Valor observado |
|---|---|
| Host | macOS arm64, Docker 29.1.3 |
| Contenedor `dev` | `python:3.12.3-slim` + binario de `ghcr.io/astral-sh/uv:0.10.9`; arquitectura `aarch64` |
| `python --version` (en `dev`) | Python 3.12.3 |
| `uv --version` (en `dev`) | uv 0.10.9 |
| `postgres` | `postgres:17.6`, healthy, `127.0.0.1:55436` |
| `pulsar` | `apachepulsar/pulsar:4.1.3` standalone, healthy, anuncia `pulsar`; admin en `127.0.0.1:18096` |

Desviaciones respecto al plan, aprobadas por el usuario:
- **uv no se instala en el host:** uv, pytest, ruff, mypy, alembic y los scripts se ejecutan en el contenedor `dev` (`docker compose exec dev …`).
- **Python viene de la imagen oficial 3.12.3:** uv no lo descarga (`UV_PYTHON_DOWNLOADS=never`).
- **Pulsar propio en el Compose de Cotizaciones:** reemplaza al del Compose de Entrada, porque ese anuncia `127.0.0.1` y no es alcanzable desde un contenedor. El puerto binario 6650 no se publica al host.

## Paso 2 — Cliente nativo de Pulsar

Entorno desechable `/tmp/pchk` dentro de `dev` (fuera del repositorio), eliminado al terminar.

| Comprobación | Resultado |
|---|---|
| Instalación | `pulsar-client 3.13.0` con `fastavro 1.12.2` |
| Wheel | `cp312-cp312-manylinux_2_28_aarch64`: hay wheel nativo para Linux arm64, no hace falta emular amd64 |
| Import | `import pulsar, _pulsar` correcto |
| Record trivial (`String` + `Integer`, ambos `required=True`) | `AvroSchema.encode` → `02780e`; `decode` devuelve `x 7` |

### Entero opcional (insumo del Paso 55)

Código fuente revisado: `pulsar/schema/definition.py` y `pulsar/schema/schema_avro.py` de la versión 3.13.0.

- **(a) Sin default explícito:** `Integer()` genera `{"name": "duracion", "type": ["null", "int"]}`, **sin** clave `default`.
- **(b) Con default:** `Integer(default=None, required_default=True)` genera `{"name": "duracion", "default": null, "type": ["null", "int"]}`. La opción `required_default` existe en 3.13.0 (`Field.__init__`, y `Record.schema_info` emite `default` solo si `field.required_default()`).
- **(c) Mensaje escrito sin el campo:**
  - Con resolución escritor v1 → lector (b), fastavro devuelve `duracion = None`.
  - Con lector (a), sin default, falla: `SchemaResolutionError: No default value for field duracion`.
  - `AvroSchema.decode(bytes)` usa solo el esquema del lector, sin resolución, y falla (`EOFError`) con bytes v1.
  - En cambio `Message.value()` llama a `AvroSchema.decode_message`, que con cliente conectado descarga el esquema del escritor por `schema_version` y resuelve contra el del lector. `_decode_bytes` además iguala el nombre de record del escritor al del lector antes de resolver.
- **(d) Construcción del Record:** si no se asigna el campo, o se asigna `None`, el valor es `None`. No hay conversión a otro valor, así que no hace falta un tipo como `BooleanOpcional` de Entrada para este caso.
- **(e) Validación:** el SDK acepta `True` en un campo `Integer`. La validación "entero estricto > 0, nunca booleano" debe hacerla el dominio (Paso 54), no el esquema.

### Consecuencias para pasos posteriores

1. **Paso 31, campos obligatorios:** todo campo de contrato que sea obligatorio debe declararse con `required=True`. Si no, el SDK lo emite como unión `["null", T]` y el `.avsc` no coincidirá con 00 §3–5.
2. **Paso 55, campo de la revisión 2:** `duracion_estimada_minutos` se declara `Integer(default=None, required_default=True)`. La prueba debe comparar el esquema contra el `.avsc` rev2.
3. **Pruebas de compatibilidad sin broker (Paso 57):** hay que usar `fastavro.schemaless_reader(buf, escritor, lector)`, no `AvroSchema.decode`, que no resuelve esquemas.

## Paso 3 — Repositorio

- El usuario inicializó git y creó el repositorio en GitHub (`origin` → `https://github.com/capbmaster/cotizaciones.git`, sin credenciales en la URL). Esto reemplaza la indicación del plan de no configurar remoto.
- `.gitignore`: el de Entrada más `*.db`, `.idea/` y `.DS_Store`. Se comprobó con `git check-ignore -v` que `.idea/`, `.venv/`, `*.db` y `.env` quedan ignorados y que `.env.example` no.
- `.python-version`: `3.12.3`.

## Paso 4 — `pyproject.toml`, lockfile y esqueleto

- `pyproject.toml` toma como plantilla el de Entrada:
  - proyecto `cotizaciones` 0.1.0, `requires-python >=3.12,<3.13`, backend `uv_build==0.10.9`;
  - las mismas dependencias y rangos de Entrada;
  - pytest con `--strict-config --strict-markers --import-mode=importlib` y `DeprecationWarning` como error en `cotizaciones.*`;
  - ruff `py312`, línea 100, reglas E/F/I/UP/B;
  - mypy strict, con `ignore_missing_imports` para `pulsar` y `disallow_subclassing_any = false` en `cotizaciones.modulos.cotizaciones.infraestructura.esquemas.*`.
- **Sin `readme` en `pyproject.toml` por ahora:** `uv_build` exige que el archivo exista y el README se crea en el Paso 9. Se añade entonces.
- Esqueleto: `src/cotizaciones/{__init__.py,py.typed}` y `tests/{,unitarias/,api/,contratos/,integracion/}__init__.py`, todos vacíos.

Comandos ejecutados en `dev`:

| Comando | Resultado |
|---|---|
| `uv lock` | `Resolved 41 packages` con CPython 3.12.3 del sistema |
| `uv sync --locked` | Crea `/opt/venv` e instala 38 paquetes |
| `uv run --locked python -c "import cotizaciones, pulsar"` | Correcto (`/app/src/cotizaciones/__init__.py`, Python 3.12.3) |
| `uv.lock` | `pulsar-client` 3.13.0 (PyPI) |

Versiones resueltas relevantes:

| Paquete | Versión |
|---|---|
| fastapi | 0.141.1 |
| starlette | 1.6.0 |
| uvicorn | 0.52.4 |
| sqlalchemy | 2.0.52 |
| psycopg / psycopg-binary | 3.3.5 |
| alembic | 1.20.0 |
| pydantic | 2.13.5 |
| fastavro | 1.12.2 |
| pytest | 9.1.1 |
| ruff | 0.16.7 |
| mypy | 2.3.1 |
| httpx2 | 2.12.0 |

El lockfile de uv es universal, así que sirve también para el CI en Ubuntu x86_64.

## Paso 5 — Configuración

Archivos: `src/cotizaciones/config/__init__.py` (vacío), `src/cotizaciones/config/settings.py`, `.env.example` y `tests/unitarias/test_settings.py`.

- `Settings` es un dataclass inmutable con los 14 campos de 00 §11. Se excluyen `PORT`, las variables de pruebas, las de Compose y `COTIZACIONES_PULSAR_ADMIN_URL`, que usan solo los scripts.
- `from_environment()` lee el entorno en cada llamada, sin caché. Una URL de base vacía o solo con espacios equivale a ausente. Un entero inválido lanza `ValueError` con el nombre de la variable.
- `__post_init__` exige:
  - los tres tópicos con prefijo `persistent://` y distintos entre sí;
  - suscripción no vacía;
  - `pool_size`, `statement_timeout_ms`, `pulsar_timeout_segundos`, `receptor_cola` y `demora_nack_ms` mayores que 0;
  - `max_overflow` ≥ 0 (0 es válido en SQLAlchemy) y `retardo_laboratorio_ms` ≥ 0.
- **Valores predeterminados en código y en `.env.example`:** los del código son los de 00 §11 (`pulsar://127.0.0.1:6650`). `.env.example` documenta en cambio los del entorno Docker (`pulsar://pulsar:6650`, admin `http://pulsar:8080`, base `postgres:5432`) y el puerto de administración publicado, 18096.

**Prueba roja:** `pytest tests/unitarias/test_settings.py` falló en la recolección con `ModuleNotFoundError: No module named 'cotizaciones.config.settings'`, antes de implementar.

Verificación (en `dev`):

| Comando | Resultado |
|---|---|
| `uv run --locked pytest tests -q` | 26 passed |
| `uv run --locked ruff check .` | All checks passed (antes de corregir, 2 × E501) |
| `uv run --locked ruff format --check .` | 21 files already formatted |
| `uv run --locked mypy src tests` | Success: no issues found in 9 source files (antes de corregir, 3 errores de tipo por `replace(**dict)` en las pruebas) |

## Paso 6 — Fábrica de base de datos

Archivos: `src/cotizaciones/config/database.py` y `tests/unitarias/test_database.py`.

- `Database` es un dataclass inmutable con `engine` y `session_factory`:
  - `close()` libera el Engine y se puede llamar varias veces;
  - `verificar()` abre una conexión corta, ejecuta `SELECT 1` y devuelve `True`, o `False` ante cualquier excepción, sin propagarla.
- `create_database(url, *, pool_size, max_overflow, statement_timeout_ms)`:
  - exige el driver `postgresql+psycopg`, si no lanza `ValueError`;
  - crea el Engine con esos límites y `pool_pre_ping=True`;
  - pasa `connect_args={"options": "-c statement_timeout=<ms>"}`;
  - no conecta al crearse.

Pruebas, sin PostgreSQL en ejecución:
- los drivers `sqlite`, `postgresql` y `postgresql+psycopg2` fallan;
- crear no llama a `psycopg.connect` y entrega sesiones independientes (adaptada de Entrada);
- el pool es `QueuePool` con `size()=3`, `max_overflow=2` y `pre_ping`;
- `statement_timeout` llega en `options` a `psycopg.connect` (se comprueba con un doble que lanza `OperationalError`);
- `verificar()` contra `127.0.0.1:1`, puerto cerrado real, devuelve `False`;
- `close()` llama a `dispose()` y admite dos llamadas.

**Prueba roja:** la recolección falló con `ModuleNotFoundError: No module named 'cotizaciones.config.database'`, antes de implementar.

Verificación (en `dev`):

| Comando | Resultado |
|---|---|
| `uv run --locked pytest tests -q` | 35 passed |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked ruff format --check .` | 23 files already formatted (antes de aplicar `ruff format`, 1 archivo por formatear) |
| `uv run --locked mypy src tests` | Success: no issues found in 11 source files |

**Observación, fuera del plan y sin aplicar:** no se fija `connect_timeout`. Si el host de la base no responde (en vez de rechazar la conexión), `verificar()` podría esperar el timeout TCP del sistema operativo. Se evaluará en la Fase 05 junto con el presupuesto de cierre de menos de 10 s.

## Paso 7 — Aplicación FastAPI con lifespan

Archivos:
- `api/__init__.py`, `infraestructura/__init__.py`, `seedwork/__init__.py` y `seedwork/aplicacion/__init__.py` (vacíos);
- `seedwork/aplicacion/excepciones.py`, con `ColisionPersistencia(RuntimeError)` copiada de Entrada;
- `infraestructura/ciclo_vida.py`, `api/app.py` y `tests/api/test_app.py`.

**`infraestructura/ciclo_vida.py`:**
- `EstadoCiclo` (StrEnum): `INICIANDO`, `OPERANDO`, `REINTENTANDO`, `PAUSADO` y `DETENIDO`.
- `EstadoComponente`: nombre, estado, último error, y el ID del mensaje y el motivo de la pausa; `resumen()` devuelve un diccionario serializable.
- `EstadoMensajeria`: la tupla de componentes, `listo()` (todos en `OPERANDO`; sin componentes es verdadero) y `resumen()` indexado por nombre.
- `procesar_mensajeria(base, configuracion)`: contexto asíncrono que en esta fase solo entrega un `EstadoMensajeria()` vacío. El Paso 38 lo completa.
- **Ubicación provisional:** `EstadoCiclo` y `EstadoComponente` viven aquí porque el Paso 7 no crea `seedwork/infraestructura/ciclos.py`. El Paso 34 los mueve a ese módulo, añade el lock y `ciclo_vida.py` pasa a importarlos, para que el seedwork no dependa de la capa de infraestructura de la app.

**`api/app.py`:**
- `create_app(settings=None, database_factory=crear_base, processing_factory=procesar_mensajeria)`. Sin `Settings`, usa `Settings.from_environment()`. `crear_base(Settings)` llama a `create_database` con los límites de la configuración.
- Lifespan:
  - si hay `database_url`, crea la `Database`, entra en el procesamiento y guarda `database` y `estado_mensajeria` en `app.state`;
  - al salir cierra primero la mensajería y después la base, también ante excepciones o si falla el arranque de la mensajería;
  - sin URL no crea nada.
- Manejadores: `SQLAlchemyError` y `ColisionPersistencia` responden 503 con "Persistencia temporalmente no disponible".
- `GET /health/live` responde 200 con `status: ok` y `service`.
- `GET /health/ready`:
  - es un endpoint síncrono, así que FastAPI lo ejecuta en su pool de hilos y `verificar()` corre fuera del event loop (lo comprueba una prueba);
  - responde 200 `{"status": "listo", "componentes": …}`;
  - o 503 `{"status": "no_listo", "motivo": base_no_configurada | base_no_disponible | mensajeria_no_operativa, "componentes": …}`;
  - no consulta ningún otro servicio.
- Título "Cotizaciones".

**Pruebas (14 nuevas, con dobles):**
- el título;
- la lectura del entorno;
- sin base: live 200, ready 503 `base_no_configurada`, y no se invocan las fábricas de base ni de procesamiento;
- ready 200 con base disponible y mensajería lista, con `verificar()` fuera del event loop;
- 503 `base_no_disponible`;
- 503 `mensajeria_no_operativa` con el resumen de la pausa;
- dos ciclos de lifespan cierran base y mensajería exactamente dos veces;
- cierre de la mensajería antes que la base, con y sin error;
- un fallo al iniciar la mensajería cierra la base;
- recursos no compartidos entre apps;
- `dependency_overrides` aislados por app;
- 503 ante `OperationalError` y `ColisionPersistencia`.

**Prueba roja:** la recolección falló con `ModuleNotFoundError: No module named 'cotizaciones.api.app'`, antes de implementar.

Verificación (en `dev`):

| Comando | Resultado |
|---|---|
| `uv run --locked pytest tests -q` | 49 passed, 1 warning |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked ruff format --check .` | 31 files already formatted |
| `uv run --locked mypy src tests` | Success: no issues found in 19 source files |

**Advertencia registrada:** Starlette 1.6.0 (`starlette/testclient.py:53`) emite `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated`. Viene de una dependencia de terceros y no de `cotizaciones.*`, así que el filtro de pytest no la convierte en error. No requiere acción nuestra.

## Paso 8 — Aislamiento de imports y verificación de distribución

Archivos: `tests/unitarias/test_aislamiento.py` y `scripts/verify_distribution.py`.

**`test_aislamiento.py`** (fusiona `test_isolation.py` y `test_aislamiento_persistencia.py` de Entrada):
- `MODULOS_SIN_MENSAJERIA` = `cotizaciones.api.app`, `cotizaciones.config.settings` y `cotizaciones.config.database`. Cada fase añade aquí sus módulos de dominio, aplicación y persistencia.
- En un subproceso `python -I`, sin variables `COTIZACIONES_*`, importa esos módulos y afirma que no quedan cargados `pulsar` ni `solicitudes_partner` (ni sus submódulos).
- **Control de la prueba:** el mismo verificador, aplicado a `import pulsar`, sí detecta `pulsar`. Así la prueba principal no puede pasar sin comprobar nada.
- En otro subproceso, con `socket.connect`, `connect_ex`, `create_connection` y `psycopg.connect` sustituidos por funciones que fallan: importar y ejecutar el lifespan sin base no abre conexiones. `/health/live` responde 200 y `/health/ready` informa `base_no_configurada`.

**`verify_distribution.py`** (copiado de Entrada y adaptado):
- Crea un entorno temporal `cotizaciones-distribution-*` con `uv sync --locked --no-editable --no-dev`, construye el wheel con `uv build` y lo reinstala sin dependencias.
- Con `python -I` desde el directorio temporal comprueba:
  - que el paquete está dentro del `sys.prefix` del entorno y fuera de `src/`;
  - que `create_app(Settings()).title == "Cotizaciones"`;
  - los imports clave de esta fase: `create_database`, `procesar_mensajeria`, `EstadoMensajeria` y `ColisionPersistencia`.

**Prueba roja:** no aplica. Las pruebas comprueban una propiedad que ya se cumplía al escribirlas. El control negativo reemplaza al rojo y demuestra que la verificación detecta un import prohibido.

Verificación (en `dev`):

| Comando | Resultado |
|---|---|
| `uv run --locked pytest tests -q` | 52 passed, 1 warning (la de Starlette/anyio) |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked ruff format --check .` | 33 files already formatted |
| `uv run --locked mypy src tests scripts` | Success: no issues found in 21 source files |
| `uv run --locked python scripts/verify_distribution.py` | Construye `cotizaciones-0.1.0-py3-none-any.whl` e imprime `Wheel instalado importado fuera del arbol fuente: /tmp/cotizaciones-distribution-bm0_7ykl/environment/lib/python3.12/site-packages/cotizaciones/__init__.py` |

`migraciones` todavía no existe, así que se omite en el comando de mypy hasta la Fase 04.

## Paso 9 — CI unitario, README y cierre

Archivos: `.github/workflows/ci.yml` y `README.md`; `pyproject.toml` recupera `readme = "README.md"`.

- **CI:** job `verificacion-unitaria` en `ubuntu-24.04`. Pasos:
  - checkout;
  - instala uv 0.10.9 con el instalador oficial versionado (`https://astral.sh/uv/0.10.9/install.sh`);
  - `uv python install` (lee `.python-version`, 3.12.3) y `uv sync --locked`;
  - ruff (check y format), mypy sobre `src tests scripts` y pytest sobre `tests/unitarias tests/api tests/contratos`;
  - `scripts/verify_distribution.py`, que el plan no pide en el CI pero se añade porque es parte de la verificación estándar.
  - Los jobs de integración y compatibilidad llegan en los Pasos 30, 42 y 57.
- **README:** propósito, estado, entorno Docker, arranque, configuración (enlace a 00 §11 y `.env.example`) y verificación estándar.

Verificación estándar completa (en `dev`, salvo `git diff --check` y el YAML, que se ejecutaron en el host):

| Comando | Resultado |
|---|---|
| `uv sync --locked` | Lockfile vigente tras añadir `readme`; solo se reconstruyó `cotizaciones` |
| `uv run --locked pytest tests -q -s --tb=short` | 52 passed, 1 warning (Starlette/anyio, de terceros) |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked ruff format --check .` | 34 files already formatted |
| `uv run --locked mypy src tests scripts` | Success: no issues found in 21 source files |
| `uv run --locked python scripts/verify_distribution.py` | `Wheel instalado importado fuera del arbol fuente: /tmp/cotizaciones-distribution-qolkgbga/environment/lib/python3.12/site-packages/cotizaciones/__init__.py` |
| `git diff --check` | Sin salida, exit 0. Solo cubre archivos ya versionados: casi todo el trabajo aún no está en seguimiento |
| YAML del CI (Ruby `YAML.load_file`, en el host) | Válido: job `verificacion-unitaria`, 8 pasos |

Arranque manual sin base (uvicorn en `dev` con `--host 0.0.0.0 --port 8002`; `curl` desde el host):

| Petición | Respuesta |
|---|---|
| `GET /health/live` | 200 `{"status":"ok","service":"cotizaciones"}` |
| `GET /health/ready` | 503 `{"status":"no_listo","motivo":"base_no_configurada","componentes":{}}` |
| `SIGTERM` al proceso uvicorn | Log: `Shutting down` → `Waiting for application shutdown.` → `Application shutdown complete.` → `Finished server process`; terminó dentro del plazo de 10 s |

El primer `curl` devolvió `(52) Empty reply from server`. El reenvío de puertos de Docker aceptó la conexión antes de que uvicorn escuchara, y `--retry-connrefused` no reintenta ese caso. Con `--retry-all-errors` respondió como se esperaba, y el log confirma que la app no falló.

## Cierre de la fase

- **Terminado:**
  - entorno reproducible en Docker;
  - paquete instalable (wheel verificado fuera de `src`);
  - `Settings` y `Database`;
  - app FastAPI con lifespan, `/health/live` y `/health/ready`;
  - aislamiento de imports (sin `pulsar` ni `solicitudes_partner`, sin conexiones al importar);
  - CI unitario definido.
- **Limitaciones:**
  - no hay procesamiento durable, consumo de Pulsar ni publicación de resultados; **todavía no se afirma capacidad para E8**;
  - `procesar_mensajeria` entrega un estado vacío;
  - el CI no se ha ejecutado en GitHub porque no se ha hecho push; su sintaxis y sus comandos se validaron localmente;
  - sigue pendiente la observación sobre `connect_timeout` (Paso 6).
- **Siguiente dependencia:** Fase 02 (Pasos 10–16), el modelo de dominio puro. Los contratos de 00 ya están fijados y la fase no necesita infraestructura.
