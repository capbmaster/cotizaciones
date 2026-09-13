# Plan de implementación — Microservicio de Cotizaciones

Fecha: 2026-09-13 (Bogotá). Estado: **plan listo para ejecutar; nada implementado**.
Destinatario: agente de IA que construirá el servicio. Leer este índice y [00-contratos-y-datos.md](00-contratos-y-datos.md) completos antes del Paso 1.

Este plan concreta, archivo por archivo, los ocho incrementos de `planes-otros-microservicios/cotizaciones/` y reproduce los patrones ya verificados en `microservicio/solicitud-partner` (Entrada). No contiene código fuente: describe qué crear, qué lógica implementar y cómo verificarla.

## Decisiones confirmadas por el usuario

| Tema | Decisión |
|---|---|
| Repositorio | `entrega_4/microservicio/cotizaciones`, repositorio git propio, hermano de `solicitud-partner`. Paquete `src/cotizaciones`, un único módulo `modulos/cotizaciones`. |
| Contrato del comando | `SolicitarCotizacion.v1` todavía no existe en Orquestación. Cotizaciones crea una copia lectora provisional (record Avro `SolicitarCotizacionV1`) y un productor doble etiquetado; entrega el `.avsc` a Orquestación, que sigue siendo la propietaria y debe adoptarlo idéntico. |
| Alcance | Servicio completo, contratos, consultas HTTP, pruebas de recuperación/concurrencia, herramientas E8/E4 propias de Cotizaciones, fase E3 (escritor v2) e imagen Docker lista para desplegar. No se aprovisiona infraestructura en la nube. |
| Plataforma | Cloud Run (un Service), Cloud SQL propio, Pulsar externo en VM (decisión D17 del equipo). Se entrega runbook y parámetros; no se ejecuta `gcloud`. |

## Fuentes y precedencia

1. Enunciado y rúbrica de la entrega 4 (4 servicios, comandos/eventos por Pulsar, HTTP solo para consultas, esquemas y evolución, topología descentralizada, CRUD, despliegue).
2. `planes-otros-microservicios/`: `00-decisiones-y-alcance.md`, `01-contratos-y-datos.md`, `02-base-de-implementacion.md`, `03-integracion-experimentos-y-entrega.md` y `cotizaciones/01…08`.
3. Código de Entrada (`microservicio/solicitud-partner/src/solicitudes_partner/`) como referencia de patrones: **se copia y adapta, nunca se importa**.
4. Este plan. Si algo aquí contradice 1 o 2, detenerse y preguntar al usuario.

## Responsabilidad del servicio

Hace: consumir `SolicitarCotizacion.v1`; resolver cada petición contra un catálogo sintético versionado; persistir una `Cotizacion` en estado PROPUESTA o RECHAZADA; publicar exactamente un hecho de resultado (`CotizacionRegistrada.v1` o `CotizacionRechazada.v1`) mediante outbox; exponer consultas HTTP de sus propias cotizaciones; sobrevivir a reentregas, reinicios, caídas (E8) y réplicas concurrentes (E4); evolucionar el escritor de `CotizacionRegistrada` (E3).

No hace: consumir directamente eventos de Entrada; llamar por HTTP a otro servicio; seleccionar la "mejor" oferta, precio de mercado, matching geográfico, visitas, pagos, ejecución o cierre del Trabajo; endpoints CRUD de catálogo; Event Sourcing; Saga/BFF (entrega 5).

## Reglas de ejecución para el agente (obligatorias)

1. Ejecutar los pasos en orden numérico. Cada paso termina con **Verificación**; no avanzar si falla.
2. Comportamiento no trivial: primero la prueba que falla (roja), luego la implementación mínima, luego refactor con pruebas verdes.
3. Prohibido importar `solicitudes_partner` o cualquier paquete de otro servicio. Cuando un paso indique "copiar de Entrada", copiar el archivo citado, cambiar el prefijo de imports a `cotizaciones.` y aplicar las adaptaciones descritas.
4. Pruebas unitarias sin red, PostgreSQL, Pulsar ni Docker. Pruebas de integración usan infraestructura real y **fallan** (nunca `skip`) si falta.
5. Sin commit, push ni tag salvo autorización explícita del usuario. Los pasos marcados **PUNTO DE CONTROL** exigen pedirla.
6. No descargar software (uv, imágenes Docker, dependencias) sin confirmar antes con el usuario; pedirlo una vez en el Paso 1 detallando qué se descargará.
7. Antes de usar flags de Pulsar, pulsar-client, uv, Alembic o Cloud Run, verificar la documentación oficial de la versión instalada. No trasladar ejemplos Java al cliente Python.
8. Nunca borrar inbox, outbox, suscripciones ni volúmenes para "desatascar" una prueba o demo.
9. Si un paso requiere una decisión no prevista (contrato, nombre, dato), detenerse y preguntar; no inventar contratos públicos.
10. Al cerrar cada fase, crear `docs/evidencias/NN-<fase>.md` con: alcance terminado, prueba roja significativa, comandos realmente ejecutados y su resultado, versiones, limitaciones y siguiente dependencia.

## Convenciones

- Identificadores propios en español sin tildes (`snake_case` para funciones/variables, `PascalCase` para clases, `MAYUSCULAS` para valores de enumeración). La base técnica replica los nombres de Entrada para facilitar la revisión cruzada: `Settings`, `create_app`, `Database`, `create_database`, `service_name`, `database_url`, `pulsar_url`.
- Nombres de contratos públicos exactamente como en [00-contratos-y-datos.md](00-contratos-y-datos.md); nunca traducirlos.
- Variables de entorno con prefijo `COTIZACIONES_`. Puerto HTTP local 8002 (en Cloud Run se usa `PORT`). PostgreSQL local en `127.0.0.1:55436`. Pulsar de desarrollo: el standalone del Compose de Entrada (`127.0.0.1:6650`, admin `127.0.0.1:18086`).
- Herramientas idénticas a Entrada: Python 3.12.3, uv 0.10.9 con backend `uv_build==0.10.9`, FastAPI, Uvicorn, SQLAlchemy 2.0, `psycopg[binary]` 3, Alembic, Pydantic 2, `pulsar-client[avro]==3.13.0`; dev: pytest, ruff, mypy (strict), httpx2. PostgreSQL 17.6 y broker Pulsar 4.1.3.
- Módulos donde `solicitudes_partner` tiene carpeta propia de dominio: aquí solo existe `modulos/cotizaciones`. El catálogo es información de referencia del caso de uso, no un segundo módulo.

## Estructura final esperada

```text
microservicio/cotizaciones/
  pyproject.toml  uv.lock  .python-version  .gitignore  .dockerignore  .env.example
  README.md  alembic.ini  docker-compose.yaml  docker-compose.imagen.yaml  Dockerfile
  .github/workflows/ci.yml
  datos/catalogos/catalogo-v1.json  catalogo-v2.json
  docs/plans/            (este plan)
  docs/contratos/        (avsc, ejemplos JSON, fixtures binarios, README, consultas, openapi.json)
  docs/evidencias/       (una por fase)
  docs/experimentos/     (procedimientos E8/E4/E3 de Cotizaciones)
  docs/despliegue/cloud-run.md
  migraciones/env.py  migraciones/versions/0001_cotizaciones.py  0002_duracion_estimada.py
  scripts/  verify_distribution.py  cargar_catalogo.py  preparar_pulsar.py  enviar_peticion.py
            consumir_resultados.py  inspeccionar_outbox.py  reconciliar.py  muestrear_metricas.py
            smoke_despliegue.py
  src/cotizaciones/
    __init__.py  py.typed
    api/  app.py  cotizaciones.py
    config/  settings.py  database.py  bootstrap.py  persistencia.py  rutas.py
    infraestructura/  ciclo_vida.py  despacho.py
    modulos/cotizaciones/
      dominio/  entidades.py  objetos_valor.py  eventos.py  servicios.py  excepciones.py  repositorios.py
      aplicacion/  comandos.py  consultas.py  excepciones.py  unidad_trabajo.py
                   handlers/procesar_peticion.py  handlers/consultar_cotizaciones.py
      infraestructura/  orm.py  mapeadores.py  serializacion.py  repositorios.py  unidad_trabajo.py
                        mapeadores_eventos.py  consumidor_peticiones.py
                        esquemas/v1/comandos.py  esquemas/v1/eventos.py  esquemas/v2/eventos.py
    seedwork/
      dominio/  entidades.py  eventos.py  objetos_valor.py  validaciones.py
      aplicacion/  excepciones.py  identificadores.py  reloj.py  reintentos.py  unidad_trabajo.py  publicacion.py
      infraestructura/  orm.py  serializacion.py  inbox.py  outbox.py  despacho_outbox.py
                        publicador_pulsar.py  ciclos.py  reloj.py  identificadores.py  unidad_trabajo_sqlalchemy.py
  tests/  unitarias/  api/  contratos/  integracion/
```

Crear únicamente los archivos que indique un paso. No crear carpetas vacías ni fachadas de reexportación.

## Índice de fases

| Archivo | Pasos | Resultado de la fase | Gate para continuar |
|---|---|---|---|
| [00](00-contratos-y-datos.md) | — | Contratos, tópicos, catálogo e IDs de laboratorio | Leído completo |
| [01](01-entorno-y-base.md) | 1–9 | Entorno reproducible, app vacía instalable, CI unitario | Checks verdes y wheel importable fuera de `src` |
| [02](02-dominio.md) | 10–16 | Agregado `Cotizacion`, catálogo y regla de selección puros | Tabla de decisiones cubierta por tests |
| [03](03-aplicacion.md) | 17–21 | Caso de uso idempotente con dobles | Rollback, duplicados y conflicto probados sin I/O |
| [04](04-persistencia.md) | 22–30 | PostgreSQL, UoW, inbox, outbox, catálogo cargable | Carreras y rollback probados en PostgreSQL real |
| [05](05-pulsar-y-ciclo-de-vida.md) | 31–42 | Consumo real, publicación de resultados, lifespan, readiness | Comando real → fila → resultado Avro decodificable |
| [06](06-consultas.md) | 43–46 | API de consulta sobre estado propio | GET real después de consumo, sin fallback |
| [07](07-recuperacion-y-escala.md) | 47–52 | Caída/recuperación, réplicas y herramientas E8/E4 | Reconciliación sin pérdidas ni duplicados |
| [08](08-evolucion-e3.md) | 53–59 | Escritor v2 compatible con `duracion_estimada_minutos` | Matriz v1/v2 y control incompatible demostrados |
| [09](09-imagen-y-despliegue.md) | 60–65 | Imagen Docker, runbook Cloud Run y guion | Imagen arranca, consume sin HTTP y cierra ante SIGTERM |

Los contratos ([00](00-contratos-y-datos.md)) se fijan antes del Paso 10. La integración con Orquestación real ocurre cuando exista; mientras tanto se usa el productor doble etiquetado (Paso 39) y se deja el pendiente explícito en la evidencia.

## Verificación estándar al cerrar cada fase

Ejecutar desde la raíz del servicio (las rutas inexistentes se omiten hasta que existan):

- `uv sync --locked`
- `uv run --locked pytest tests -q -s --tb=short`
- `uv run --locked ruff check .` y `uv run --locked ruff format --check .`
- `uv run --locked mypy src tests scripts migraciones`
- `uv run --locked python scripts/verify_distribution.py`
- `git diff --check`

## Riesgos detectados durante el análisis y su mitigación

| Riesgo | Dónde se resuelve |
|---|---|
| Este equipo es macOS arm64 sin `uv`; Entrada solo se probó en Ubuntu x86_64. `pulsar-client` 3.13.0 puede no tener wheel para esta plataforma. | Paso 2: verificar import nativo antes de fijar nada; alternativa en contenedor Linux. |
| Nombres de record Avro no fijados para el comando y el rechazo; nombres distintos entre productor y lector hacen que Pulsar rechace el esquema. | [00](00-contratos-y-datos.md) fija nombres; Paso 42 entrega el `.avsc` a Orquestación. |
| `categoria` es texto libre en Entrada (solo se valida no vacía). | Regla de normalización en [00](00-contratos-y-datos.md) y Paso 11. |
| El ciclo de Entrada espera 0,2 s después de **cada** paso, lo que limita el despacho a ~5 mensajes/s por instancia y distorsionaría E4. | Paso 34: pausar solo cuando no hubo trabajo. |
| El consumidor de Entrada hace NACK y reintenta sin fin ante datos inválidos; la base común exige pausar el bucle y marcar readiness. | Pasos 34, 36 y 38. |
| El SDK podría no emitir `"default": null` para un entero opcional o convertir `None` en otro valor (Entrada tuvo que crear `BooleanOpcional`). | Paso 55: verificación explícita antes de publicar v2. |
| Un único hilo de despacho debe publicar en dos tópicos. | Paso 35: publicador enrutado por destino. |
