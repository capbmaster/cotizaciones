# Fase 01 — Entorno y base tecnológica (Pasos 1–9)

Corresponde a `planes-otros-microservicios/cotizaciones/01-base-tecnologica.md`. Resultado: paquete instalable, app FastAPI vacía con lifespan, pruebas aisladas y CI unitario. Todavía no hay procesamiento durable.

---

## Paso 1 — Preparar herramientas locales (PUNTO DE CONTROL: autorización de descarga)

**Contexto verificado:** este equipo es macOS arm64, con Docker 29.1.3 y **sin `uv`**. `solicitud-partner` no tiene `.venv`.

**Acción:**
1. Pedir autorización al usuario para descargar e instalar: uv 0.10.9 (instalador oficial de Astral), Python 3.12.3 administrado por uv, imagen `postgres:17.6` y, si no existe localmente, `apachepulsar/pulsar:4.1.3` (la levanta el Compose de Entrada).
2. Con autorización, instalar uv siguiendo https://docs.astral.sh/uv/getting-started/installation/ y asegurar que el binario queda en el `PATH` del shell no interactivo.

**Verificación:** `uv --version` informa 0.10.9; `docker --version` responde. Registrar ambas salidas para la evidencia 01.

## Paso 2 — Comprobar el cliente nativo de Pulsar en esta plataforma

**Objetivo:** descubrir al principio si `pulsar-client[avro]==3.13.0` tiene wheel para Python 3.12 en macOS arm64, y registrar el comportamiento del SDK con enteros opcionales (se usará en el Paso 55).

**Acción (en un entorno desechable dentro del directorio scratch, fuera del repositorio):**
1. Crear con uv un entorno temporal con Python 3.12.3 e instalar `pulsar-client[avro]==3.13.0`.
2. Comprobar: el módulo `pulsar` se importa; un Record Avro trivial se codifica y decodifica con `AvroSchema`.
3. Registrar, para un Record con un campo entero opcional: (a) el esquema JSON que genera el SDK sin default explícito; (b) el esquema con default `None` y la opción del SDK que obliga a emitir el default (en 3.13.0 se llama `required_default`; confirmarlo en el código fuente de `pulsar/schema/definition.py` de esa versión); (c) qué valor devuelve al decodificar un mensaje escrito sin ese campo.

**Si no hay wheel o el import falla:** detenerse e informar al usuario. Alternativa propuesta: ejecutar `uv`, pruebas y scripts dentro de un contenedor `python:3.12.3-slim` (plataforma `linux/amd64`) con el repositorio montado. Documentar la opción elegida en el README antes de seguir.

**Verificación:** nota en la evidencia 01 con plataforma, versión instalada y los tres resultados del punto 3.

## Paso 3 — Crear el repositorio

**Archivos:** `.gitignore`, `.python-version`.

**Acción:**
1. La carpeta `microservicio/cotizaciones` ya contiene `docs/plans/` (este plan); no borrarla. Inicializar git con rama `main`.
2. `.gitignore`: copiar el de Entrada y verificar que ignora `.venv/`, `__pycache__/`, `dist/`, cachés de pytest/mypy/ruff, `*.db` y `.env`.
3. `.python-version` con `3.12.3`.
4. No configurar remoto. Si el usuario lo pide, usar una URL sin credenciales (el remoto de Entrada contiene un token incrustado; no replicar esa práctica).

**Verificación:** `git status` muestra los archivos sin seguimiento; `git remote -v` está vacío.

## Paso 4 — `pyproject.toml`, lockfile y esqueleto del paquete

**Archivos:** `pyproject.toml`, `uv.lock`, `src/cotizaciones/__init__.py` (vacío), `src/cotizaciones/py.typed` (vacío), `tests/__init__.py`, `tests/unitarias/__init__.py`, `tests/api/__init__.py`, `tests/contratos/__init__.py`, `tests/integracion/__init__.py`.

**Contenido de `pyproject.toml`** (tomar como plantilla el de Entrada y cambiar solo lo indicado):
- Proyecto `cotizaciones`, versión `0.1.0`, descripción "Cotizaciones — Hogar de los Alpes", `requires-python` `>=3.12,<3.13`.
- Dependencias con los mismos rangos que Entrada: fastapi, uvicorn, sqlalchemy 2.0.x, `psycopg[binary]`, alembic, `pulsar-client[avro]==3.13.0`, pydantic 2. Grupo dev: pytest, ruff, mypy, httpx2.
- Backend `uv_build==0.10.9`.
- pytest: `testpaths = ["tests"]`, opciones `--strict-config --strict-markers --import-mode=importlib`, y DeprecationWarning como error para `cotizaciones.*`.
- ruff: `py312`, línea 100, reglas E, F, I, UP, B.
- mypy: `strict`; `ignore_missing_imports` para `pulsar` y `pulsar.*`; `disallow_subclassing_any = false` para `cotizaciones.modulos.cotizaciones.infraestructura.esquemas.*`.

**Acción:** `uv lock` y luego `uv sync --locked`.

**Verificación:** `uv run --locked python -c "import cotizaciones, pulsar"` termina sin error; `uv.lock` contiene `pulsar-client` 3.13.0.

## Paso 5 — Configuración (`config/settings.py`, `.env.example`)

**Archivos:** `src/cotizaciones/config/__init__.py`, `src/cotizaciones/config/settings.py`, `.env.example`, `tests/unitarias/test_settings.py`.

**Lógica:**
- `Settings`: dataclass inmutable con un campo por variable de [00 §11](00-contratos-y-datos.md) (menos las de pruebas y `PORT`): `service_name`, `database_url` (opcional), `pool_size`, `max_overflow`, `statement_timeout_ms`, `pulsar_url`, `topico_peticiones`, `suscripcion_peticiones`, `topico_registrada`, `topico_rechazada`, `pulsar_timeout_segundos`, `receptor_cola`, `demora_nack_ms`, `retardo_laboratorio_ms`.
- Método de clase `from_environment()` que lee el entorno en cada llamada (sin caché global). URL vacía o solo con espacios equivale a ausente.
- Validaciones de `__post_init__` según 00 §11, lanzando `ValueError` con mensaje en español.

**Pruebas (primero en rojo):** valores predeterminados; lectura desde variables de entorno (usar `monkeypatch`); tópico sin `persistent://` falla; tópicos repetidos fallan; suscripción vacía falla; pool o timeout no positivos fallan.

**Verificación:** `uv run --locked pytest tests/unitarias/test_settings.py -q` verde.

## Paso 6 — Factoría de base de datos (`config/database.py`)

**Archivos:** `src/cotizaciones/config/database.py`, `tests/unitarias/test_database.py`.

**Lógica (adaptar `config/database.py` de Entrada):**
- `Database`: dataclass inmutable con `engine`, `session_factory` y métodos `close()` (libera el Engine) y `verificar()` (abre una conexión corta, ejecuta una consulta trivial y devuelve verdadero o falso sin propagar excepciones; se usa en readiness).
- `create_database(url, *, pool_size, max_overflow, statement_timeout_ms)`: exige el driver `postgresql+psycopg` (si no, `ValueError`), crea el Engine con esos límites, `pool_pre_ping` activo y el `statement_timeout` de PostgreSQL pasado como opción de conexión. **No conecta al crearse.**

**Pruebas:** driver distinto falla; crear la base con una URL hacia un puerto cerrado no lanza error (prueba que no conecta); `verificar()` sobre esa URL devuelve falso; `close()` se puede llamar dos veces.

**Verificación:** pruebas verdes sin PostgreSQL en ejecución.

## Paso 7 — Aplicación FastAPI con lifespan (`api/app.py`, `infraestructura/ciclo_vida.py`)

**Archivos:** `src/cotizaciones/api/__init__.py`, `src/cotizaciones/api/app.py`, `src/cotizaciones/infraestructura/__init__.py`, `src/cotizaciones/infraestructura/ciclo_vida.py`, `src/cotizaciones/seedwork/__init__.py`, `src/cotizaciones/seedwork/aplicacion/__init__.py`, `src/cotizaciones/seedwork/aplicacion/excepciones.py` (copiar `ColisionPersistencia` de Entrada), `tests/api/test_app.py`.

**Lógica de `infraestructura/ciclo_vida.py` en esta fase:**
- Tipo `EstadoMensajeria`: registro de componentes de mensajería. Cada componente expone nombre y estado (`INICIANDO`, `OPERANDO`, `REINTENTANDO`, `PAUSADO`, `DETENIDO`), último error y, si está pausado, el ID del mensaje y el motivo. Método `listo()`: verdadero si todos los componentes requeridos están en `OPERANDO`. Método `resumen()`: diccionario serializable para la respuesta HTTP.
- `procesar_mensajeria(base, configuracion)`: contexto asíncrono que en esta fase solo entrega un `EstadoMensajeria` vacío. El Paso 38 lo completa; no crear otro punto de arranque.

**Lógica de `api/app.py` (seguir la estructura de Entrada):**
- `create_app(settings=None, database_factory=..., processing_factory=procesar_mensajeria)`. Si no recibe `Settings`, llama `Settings.from_environment()`. `database_factory` recibe `Settings` y devuelve `Database`.
- Lifespan: si hay `database_url`, crear `Database`, entrar en `processing_factory(base, settings)` y guardar `database` y `estado_mensajeria` en `app.state`; al salir, cerrar mensajería y después la base, también ante excepciones. Sin URL: no crea base ni mensajería.
- Manejadores de excepción: errores de SQLAlchemy y `ColisionPersistencia` → 503 con detalle "Persistencia temporalmente no disponible".
- `GET /health/live` → 200 con `status: ok` y `service`.
- `GET /health/ready` → ejecuta `database.verificar()` fuera del event loop (en un hilo) y consulta `estado_mensajeria.listo()`. 200 con `status: listo` y el resumen de componentes; 503 con `status: no_listo` y motivo (`base_no_configurada`, `base_no_disponible` o `mensajeria_no_operativa`) más el resumen. No consulta ningún otro microservicio.
- Título de la app: "Cotizaciones".

**Pruebas (con dobles, sin red):** sin base, live responde 200 y ready 503 `base_no_configurada`, y la factoría de procesamiento no se invoca; con un doble de `Database` cuyo `verificar()` devuelve verdadero, un procesamiento falso que cuenta entradas y salidas y un estado listo, ready responde 200; si `verificar()` devuelve falso, 503 `base_no_disponible`; entrar y salir del lifespan dos veces cierra la base y la mensajería exactamente dos veces.

**Verificación:** `uv run --locked pytest tests/api -q` verde.

## Paso 8 — Aislamiento de imports y verificación de distribución

**Archivos:** `tests/unitarias/test_aislamiento.py`, `scripts/verify_distribution.py`.

**Lógica:**
- Prueba de aislamiento: en un subproceso con Python aislado, importar `cotizaciones.api.app`, `cotizaciones.config.settings` y `cotizaciones.config.database`; afirmar que ni `pulsar` ni `solicitudes_partner` aparecen en los módulos cargados. Cada fase posterior añade a esta lista los módulos de dominio, aplicación y persistencia que cree.
- `scripts/verify_distribution.py`: copiar el de Entrada y cambiar el prefijo del directorio temporal, el paquete importado y las aserciones. En esta fase verifica que el paquete se importa desde el entorno instalado (no desde `src`) y que `create_app(Settings())` tiene título "Cotizaciones". Cada fase añade los imports clave que cree.

**Verificación:** `uv run --locked python scripts/verify_distribution.py` imprime la ruta del paquete instalado fuera del árbol fuente.

## Paso 9 — CI unitario, README inicial y evidencia

**Archivos:** `.github/workflows/ci.yml`, `README.md`, `docs/evidencias/01-entorno-y-base.md`.

**Lógica:**
- Workflow con un job `verificacion-unitaria` en Ubuntu: checkout, uv 0.10.9 fijado, `uv sync --locked`, ruff (check y format), mypy y pytest sobre `tests/unitarias`, `tests/api` y `tests/contratos`. Los jobs de integración y compatibilidad se añaden en los Pasos 30, 42 y 57.
- README: propósito, estado, instalación (`uv sync --locked`), arranque (`uv run --locked uvicorn cotizaciones.api.app:create_app --factory --port 8002`), variables de entorno (enlace a 00 §11) y verificación estándar.

**Verificación:** verificación estándar completa (ver [README](README.md)); `curl` a `http://127.0.0.1:8002/health/live` devuelve 200 con el servidor arrancado sin base. Escribir la evidencia 01. Todavía no afirmar procesamiento durable ni capacidad para E8.
