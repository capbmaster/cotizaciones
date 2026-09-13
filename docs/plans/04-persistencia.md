# Fase 04 — PostgreSQL, UoW, inbox, outbox y catálogo (Pasos 22–30)

Corresponde a `planes-otros-microservicios/cotizaciones/04-postgresql-uow-outbox.md`. Resultado: cada resolución, su marca de inbox y su salida se confirman atómicamente en la base propia de Cotizaciones y resisten réplicas concurrentes. Modelo de datos: CRUD relacional (D06); inbox, outbox y el archivo de eventos no son un event store.

---

## Paso 22 — Base local y Alembic

**Archivos:** `docker-compose.yaml`, `alembic.ini`, `migraciones/env.py`.

**Contenido:**
- Compose con proyecto `cotizaciones` y un único servicio `postgres` (imagen `postgres:17.6`, usuario `cotizaciones`, contraseña de laboratorio `cotizaciones_local`, base `cotizaciones`), publicado solo en `127.0.0.1:${COTIZACIONES_POSTGRES_PORT:-55436}`, volumen propio `cotizaciones_postgres` y healthcheck con `pg_isready`. **No incluir Pulsar:** en desarrollo se usa el del Compose de Entrada, porque dos Compose no pueden publicar ambos el puerto 6650.
- `alembic.ini`: copiar el de Entrada.
- `migraciones/env.py`: copiar el de Entrada. Cambiar la variable a `COTIZACIONES_DATABASE_URL` y tomar `metadata` de `cotizaciones.config.persistencia`. Conservar el soporte de conexión inyectada, que usan las pruebas.

**Verificación:** `docker compose -f docker-compose.yaml up -d --wait` deja PostgreSQL saludable en 55436.

## Paso 23 — Seedwork de infraestructura SQL

**Archivos:** `src/cotizaciones/seedwork/infraestructura/{orm,serializacion,inbox,outbox,despacho_outbox,unidad_trabajo_sqlalchemy}.py`.

**Acción (copiar de Entrada y adaptar):**
- `orm.py` y `serializacion.py` (`Documento` y los lectores tipados `texto`, `entero`, `objeto`, `identidad`, `instante`): sin cambios.
- `inbox.py`: la columna clave se llama `id_mensaje` (no `id_evento`) y el conflicto de contenido lanza `ConflictoMensaje`. Mismo mecanismo: inserción que ignora conflicto, releer y comparar documento.
- `outbox.py`: copiar completo (`EventoSQL` como archivo de eventos, `SalidaSQL`, `Reserva` con token/propietario/vencimiento, `RepositorioOutbox` con reclamar mediante bloqueo que salta filas ya bloqueadas, confirmar/reprogramar condicionados al token, inspección y métricas, y `RepositorioSalidasSQL` con ID de salida determinista por evento y destino).
- `despacho_outbox.py`: copiar `DespachadorOutbox`, pero `despachar_lote` recibe el límite como parámetro con valor predeterminado 20 y **devuelve cuántas confirmó** (el ciclo del Paso 34 usa ese número para decidir si pausa).
- `unidad_trabajo_sqlalchemy.py`: copiar `UnidadTrabajoSQL`. Sustituir su `preparar_entrada(consumidor, evento)` por la versión genérica `preparar_entrada(consumidor, id_mensaje, documento)`, que delega en `inbox.preparar` con la misma sesión. Conservar `restricciones_reintentables` y la conversión de violaciones UNIQUE en `ColisionPersistencia`.

## Paso 24 — Migración `0001_cotizaciones.py`

**Archivo:** `migraciones/versions/0001_cotizaciones.py` (revisión `0001`), escrita a mano con SQL, como en Entrada. Crea los esquemas `cotizaciones` y `mensajeria`. El downgrade elimina todo en orden inverso.

**`cotizaciones.catalogos`:** `version` (entero, clave primaria, > 0); `huella` (texto no nulo: SHA-256 del contenido normalizado); `cargado_en` (instante, por defecto ahora); `activo` (booleano, por defecto falso). Índice único parcial `uq_catalogo_activo` sobre `activo` solo cuando es verdadero: garantiza una sola versión activa.

**`cotizaciones.ofertas_catalogo`:** `id` (UUID, clave primaria determinista, ver Paso 27); `version_catalogo` (clave foránea a `catalogos`); `id_proveedor` (UUID); `categoria` (texto normalizado); `tipo_red` (restricción a los dos valores); `id_partner` (UUID opcional); `importe_menor` (BIGINT > 0); `moneda` (tres letras mayúsculas). Restricción `ck_oferta_red_partner` (general sin partner, homologada con partner). Restricción única `uq_oferta_catalogo` sobre versión, categoría, red, partner y proveedor con NULLS NOT DISTINCT (disponible en PostgreSQL 17). Índice por versión y categoría.

**`cotizaciones.cotizaciones`:**

| Columna | Tipo / regla |
|---|---|
| `id` | UUID, clave primaria (`id_cotizacion`) |
| `id_peticion` | UUID no nulo, restricción única `uq_cotizacion_peticion` |
| `id_trabajo`, `id_solicitud`, `id_partner` | UUID no nulos; índice por `id_trabajo` |
| `peticion` | JSONB no nulo: copia canónica de `DatosPeticion` |
| `id_comando_origen`, `correlacion`, `causacion` | UUID no nulos |
| `instante_comando` | instante no nulo (del envelope; sirve para medir latencia) |
| `version_catalogo` | entero, clave foránea a `catalogos` |
| `version_cotizacion` | entero, restricción = 1 |
| `estado` | `PROPUESTA` o `RECHAZADA` |
| `id_proveedor`, `importe_menor`, `moneda` | nulos salvo en propuesta |
| `motivo` | nulo salvo en rechazo; restricción a los dos motivos |
| `resuelta_en` | instante no nulo (reloj del dominio) |
| `registrada_en` | instante no nulo, por defecto la hora del servidor al insertar (métricas) |

Restricción `ck_cotizacion_resultado`: en propuesta, proveedor, importe > 0 y moneda presentes y motivo nulo; en rechazo, lo contrario. Índice por `resuelta_en` e `id` para listados estables.

**`mensajeria.inbox`:** `nombre_consumidor` + `id_mensaje` como clave primaria compuesta, `documento` JSONB y `procesada_en`. **`mensajeria.outbox`:** idéntica a la de Entrada, incluidas `uq_salida_destino` e `ix_salida_pendiente`. **`mensajeria.eventos`:** `id_evento` como clave primaria y `documento` JSONB.

## Paso 25 — ORM y mapeadores SQL

**Archivos:** `modulos/cotizaciones/infraestructura/{__init__,orm,mapeadores}.py`.

- `orm.py`: `CatalogoSQL`, `OfertaCatalogoSQL` y `CotizacionSQL`, que reflejan exactamente las columnas del Paso 24 y usan `BaseSQL` del seedwork.
- `mapeadores.py`: conversión entre el agregado y un diccionario de valores de columna; reconstrucción de `Cotizacion` desde la fila **sin registrar eventos**; construcción de `CatalogoVigente` desde las filas de catálogo y ofertas. Si los datos violan invariantes del dominio, lanza `CatalogoInvalido`. Este archivo no importa nada de Pulsar.

## Paso 26 — Serialización de documentos

**Archivos:** `modulos/cotizaciones/infraestructura/serializacion.py`, `tests/unitarias/test_serializacion.py`.

- Petición: `DatosPeticion` ↔ documento con UUID como texto y enumeraciones por valor.
- Comando (documento del inbox): `command_id`, `instante` en UTC, `correlacion`, `causacion` y `datos` (documento de la petición). Dos comandos iguales producen documentos idénticos.
- Eventos de dominio ↔ documento con `tipo` (nombre de la clase), `version_formato` 1, `id_evento`, `instante`, `id_cotizacion`, `peticion`, `id_comando`, `correlacion`, `version_catalogo`, `version_cotizacion` y, según el tipo, `id_proveedor`, `importe_menor` y `moneda`, o bien `motivo`. Un formato o tipo desconocido lanza `ValueError`. Serializar valida decodificando de vuelta (como hace `config/serializacion.py` de Entrada).

**Pruebas:** ida y vuelta exacta de ambos eventos y del comando; el importe conserva su valor entero exacto; formato 2 todavía desconocido falla (el Paso 54 lo habilita).

## Paso 27 — Repositorios SQL

**Archivo:** `modulos/cotizaciones/infraestructura/repositorios.py` (toda la SQL del módulo vive aquí).

- `RepositorioCotizacionesSQL` (recibe la sesión de la UoW): `obtener_por_peticion` consulta por `id_peticion` y reconstruye; `guardar` inserta y hace flush. Una violación UNIQUE se propaga: la UoW la convierte en `ColisionPersistencia`.
- `RepositorioCatalogoSQL` (recibe la sesión): `obtener_vigente` lee la versión activa y sus ofertas ordenadas por proveedor, o devuelve nada. `registrar_version(catalogo, huella)` inserta catálogo y ofertas. Si la versión ya existe, compara la huella: igual significa operación sin efecto y devuelve falso; distinta lanza `CatalogoInvalido`. `activar(version)` desactiva la versión activa y activa la indicada en la misma transacción; una versión inexistente es error. Las versiones nunca se modifican ni se borran.
- ID de cada oferta: UUID versión 5 con un espacio de nombres constante del módulo, calculado sobre el texto «versión|categoría|red|partner|proveedor».

## Paso 28 — Unidad de trabajo SQL

**Archivo:** `modulos/cotizaciones/infraestructura/unidad_trabajo.py`.

`UnidadTrabajoCotizacionesSQL` hereda `UnidadTrabajoSQL`:
- `restricciones_reintentables` = { `uq_cotizacion_peticion` };
- al abrirse, crea ambos repositorios con la misma sesión;
- `registrar_recepcion(consumidor, comando)` serializa el comando y llama al `preparar_entrada` genérico con el `id_comando`.

Carreras cubiertas: dos réplicas con el mismo `command_id` → la segunda espera el commit de la primera sobre la clave del inbox y termina sin efecto. Dos réplicas con distinto `command_id` y la misma petición → la segunda choca con `uq_cotizacion_peticion`, se reintenta, encuentra la cotización, compara datos y solo añade su marca de inbox.

## Paso 29 — Rutas, persistencia y bootstrap SQL

**Archivos:** `config/rutas.py`, `config/persistencia.py`, `config/bootstrap.py` (ampliación).

- `rutas.py`: las constantes de destino de [00 §7](00-contratos-y-datos.md), la tupla de destinos admitidos y `destinos_evento(evento)`, que resuelve por tipo de evento y lanza `ValueError` si el evento no tiene ruta.
- `persistencia.py`: expone `metadata` (para Alembic y pruebas); `crear_uow_cotizaciones(base)` construye la UoW con la serialización de eventos y las rutas; `verificar_destinos(base)` impide arrancar si el outbox tiene pendientes con destinos desconocidos (copiar de Entrada).
- `bootstrap.py`: `componer_procesamiento_sql(base)` construye el handler con la UoW SQL, `RelojActual` e `IdentificadoresAleatorios`.

## Paso 30 — Carga de catálogo, pruebas PostgreSQL, CI y evidencia

**Archivos:** `datos/catalogos/catalogo-v1.json`, `scripts/cargar_catalogo.py`, `scripts/inspeccionar_outbox.py`, `tests/integracion/conftest.py`, `tests/integracion/test_{migraciones,repositorios,catalogo,unidad_trabajo,concurrencia,outbox}.py`, ampliación de `.github/workflows/ci.yml`, `docs/evidencias/04-persistencia.md`.

**Datos:** `catalogo-v1.json` contiene exactamente las cinco ofertas de 00 §9, sin la clave de duración.

**`cargar_catalogo.py`:** argumentos `--archivo` (por defecto el catálogo v1) y `--activar`. Lee el JSON, construye y valida las ofertas con el dominio (normalizando la categoría) y calcula la huella sobre un JSON canónico (claves ordenadas, categorías normalizadas, ofertas ordenadas). En una sola UoW registra la versión y, si se pidió, la activa. Informa la versión, la cantidad de ofertas, si era nueva o ya existía, y la versión activa. Termina con código 2 si la versión existía con otro contenido. Lee `COTIZACIONES_DATABASE_URL`.

**`inspeccionar_outbox.py`:** copiar el de Entrada, adaptado.

**`conftest.py`:** copiar el de Entrada, con `COTIZACIONES_TEST_DATABASE_URL`, bases temporales `cotizaciones_test_<uuid>` migradas a head y eliminadas al final, y truncado de tablas entre pruebas. Añadir un fixture que cargue y active el catálogo v1.

**Pruebas (PostgreSQL real; SQLite no sustituye ninguna):**
1. Migraciones: upgrade desde vacío, downgrade a base y upgrade otra vez; existen las restricciones con nombre.
2. Repositorios: ida y vuelta exacta de propuesta y rechazo; reconstruir no produce eventos.
3. Catálogo: el script es idempotente; misma versión con otro contenido termina con código 2; activar cambia la versión activa y nunca hay dos activas; una cotización previa conserva su `version_catalogo` después de activar otra versión.
4. UoW: un fallo al guardar la salida revierte cotización, inbox y salida; `CatalogoNoDisponible` no deja nada.
5. Concurrencia con dos hilos sincronizados por una barrera: mismo `command_id` → una cotización, una marca y una salida; distinto `command_id` y misma petición → una cotización, dos marcas y una salida; datos contradictorios → `ConflictoPeticion` sin escrituras extra.
6. Outbox: una reserva vencida no se confirma con el token anterior; dos despachadores no reservan la misma fila; una publicación repetida conserva el mismo `id_evento` y documento.

**CI:** añadir el job `integracion-postgres` con PostgreSQL 17.6 como contenedor de servicio, que ejecute `tests/integracion` excepto los módulos que requieren Pulsar (el Paso 42 los incorpora).

**Verificación:** verificación estándar con PostgreSQL arriba. La evidencia 04 muestra una fila empresarial y una salida por petición bajo carrera, y cero marcas de inbox sin efecto.
