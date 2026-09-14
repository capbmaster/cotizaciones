# Evidencia 04 — PostgreSQL, UoW, inbox, outbox y catálogo

Estado: **Fase 04 terminada** (Pasos 22–30). Fecha: 2026-09-14 (Bogotá). Entorno: contenedor `dev` (Python 3.12.3, uv 0.10.9, aarch64); PostgreSQL 17.6 del Compose; SQLAlchemy 2.0.52; Alembic 1.20.0; psycopg 3.3.5.

Cada resolución, su marca de inbox y su salida se confirman atómicamente en la base propia de Cotizaciones y resisten réplicas concurrentes. El modelo es CRUD relacional (D06): inbox, outbox y archivo de eventos no son un event store. **Todavía no hay Pulsar**: las salidas quedan pendientes hasta la Fase 05.

## Alcance terminado

| Paso | Archivos | Contenido |
|---|---|---|
| 22 | `docker-compose.yaml` (ya existía), `alembic.ini`, `migraciones/env.py` | `postgres` en `127.0.0.1:55436`, volumen propio y healthcheck `pg_isready`. `alembic.ini` copiado de Entrada. `env.py` lee `COTIZACIONES_DATABASE_URL`, toma `metadata` de `config.persistencia`, conserva la conexión inyectada que usan las pruebas y usa `statement_timeout` de 60 s para migrar. |
| 23 | `seedwork/infraestructura/{orm,serializacion,inbox,outbox,despacho_outbox,unidad_trabajo_sqlalchemy}.py` | Copiados de Entrada. El inbox usa la clave `id_mensaje` y lanza `ConflictoMensaje`. `DespachadorOutbox.despachar_lote(limite=20)` devuelve cuántas confirmó. `UnidadTrabajoSQL.preparar_entrada(consumidor, id_mensaje, documento)` es genérica. Se conservan las reservas con token, propietario y vencimiento, `restricciones_reintentables` y la conversión de UNIQUE a `ColisionPersistencia`. |
| 24 | `migraciones/versions/0001_cotizaciones.py` | SQL escrito a mano. Esquemas `cotizaciones` (`catalogos`, `ofertas_catalogo`, `cotizaciones`) y `mensajeria` (`inbox`, `outbox`, `eventos`), con restricciones e índices con nombre; el downgrade elimina todo en orden inverso. |
| 25 | `infraestructura/{orm,mapeadores}.py` | `CatalogoSQL`, `OfertaCatalogoSQL` y `CotizacionSQL`, idénticos a la migración (lo comprueba `compare_metadata`). Los mapeadores reconstruyen `Cotizacion` sin eventos y `CatalogoVigente` con el dominio; datos inválidos → `CatalogoInvalido`. Sin imports de Pulsar. |
| 26 | `infraestructura/serializacion.py` | Petición, comando (documento del inbox) y eventos (`version_formato` 1); serializar valida decodificando de vuelta. Añade `catalogo_desde_documento` (lector de `catalogo-vN.json`) y `huella_catalogo` (SHA-256 del JSON canónico). |
| 27 | `infraestructura/repositorios.py` | `RepositorioCotizacionesSQL` (`obtener_por_peticion`; `guardar` con flush). `RepositorioCatalogoSQL`: `obtener_vigente` con ofertas ordenadas por proveedor; `registrar_version`, que devuelve falso con la misma huella y lanza `CatalogoInvalido` con otra; `activar`, que desactiva la anterior y activa la nueva en la misma transacción. `id_oferta` = UUID v5 de «versión\|categoría\|red\|partner\|proveedor». |
| 28 | `infraestructura/unidad_trabajo.py` | `UnidadTrabajoCotizacionesSQL`: `restricciones_reintentables = {uq_cotizacion_peticion}`, ambos repositorios sobre la misma sesión y `registrar_recepcion` → `preparar_entrada(id_comando, serializar_comando(...))`. |
| 29 | `config/{rutas,persistencia,bootstrap}.py` | Destinos de 00 §7 y `destinos_evento` (sin ruta → `ValueError`). `metadata`, `crear_uow_cotizaciones` y `verificar_destinos`. `componer_procesamiento_sql(base)` con la UoW SQL, `RelojActual` e `IdentificadoresAleatorios` (import de persistencia diferido: `bootstrap` sigue sin cargar SQLAlchemy). |
| 30 | `datos/catalogos/catalogo-v1.json`, `scripts/{cargar_catalogo,inspeccionar_outbox}.py`, `tests/integracion/*`, CI, README | Catálogo v1 con las cinco ofertas de 00 §9, sin clave de duración. Script de carga idempotente (código 2 si la versión existe con otro contenido, código 1 si el archivo es inválido). Seis módulos de integración y job `integracion-postgres`. |

### Migración 0001: tablas y restricciones

| Tabla | Restricciones e índices |
|---|---|
| `cotizaciones.catalogos` | PK `version`, `ck_catalogo_version` (> 0), `huella`, `cargado_en`, `activo`; índice único parcial `uq_catalogo_activo ON (activo) WHERE activo` (una sola versión activa) |
| `cotizaciones.ofertas_catalogo` | `fk_oferta_catalogo`, `ck_oferta_tipo_red`, `ck_oferta_importe` (> 0, BIGINT), `ck_oferta_moneda` (`^[A-Z]{3}$`), `ck_oferta_red_partner`, `uq_oferta_catalogo UNIQUE NULLS NOT DISTINCT (version_catalogo, categoria, tipo_red, id_partner, id_proveedor)`, `ix_oferta_version_categoria` |
| `cotizaciones.cotizaciones` | Las columnas del Paso 24 (petición canónica en JSONB, origen del comando, `instante_comando`, `resuelta_en`, `registrada_en DEFAULT now()`), `uq_cotizacion_peticion`, `fk_cotizacion_catalogo`, `ck_cotizacion_version` (= 1), `ck_cotizacion_estado`, `ck_cotizacion_motivo`, `ck_cotizacion_resultado`, `ix_cotizacion_trabajo`, `ix_cotizacion_resuelta (resuelta_en, id)` |
| `mensajeria.inbox` | PK (`nombre_consumidor`, `id_mensaje`), `documento` JSONB, `procesada_en` |
| `mensajeria.outbox` | Idéntica a Entrada: `uq_salida_destino`, `ix_salida_pendiente` |
| `mensajeria.eventos` | PK `id_evento`, `documento` JSONB (archivo de eventos) |

**Dos detalles de PostgreSQL resueltos en las CHECK:**
- **Una CHECK pasa cuando su expresión da NULL.** Por eso `ck_cotizacion_resultado` exige `importe_menor IS NOT NULL AND importe_menor > 0`. Sin eso, una PROPUESTA sin importe pasaría.
- **Cuando se violan varias CHECK, se informa la primera en orden alfabético.** Por eso `ck_oferta_red_partner` se escribe como dos implicaciones (`(red <> GENERAL OR partner IS NULL) AND (red <> HOMOLOGADA OR partner IS NOT NULL)`): una red desconocida solo viola `ck_oferta_tipo_red`. Las pruebas comprueban el nombre exacto de cada restricción violada.

## Prueba roja

Con las pruebas escritas y sin implementación, `pytest tests` falló en la recolección:

```text
E   ImportError: cannot import name 'componer_procesamiento_sql' from 'cotizaciones.config.bootstrap'
E   ModuleNotFoundError: No module named 'cotizaciones.config.rutas'
E   ModuleNotFoundError: No module named 'cotizaciones.modulos.cotizaciones.infraestructura'
ERROR tests/integracion - ImportError: cannot import name 'componer_procesami...
ERROR tests/unitarias/test_rutas.py
ERROR tests/unitarias/test_serializacion.py
3 errors in 0.41s
```

**Rojo significativo tras implementar: 323 passed, 2 failed.** Las dos pruebas que comparan la migración con el ORM (`compare_metadata`) fallaban con 7 diferencias: `remove_table` de `catalogos`, `ofertas_catalogo` y `cotizaciones`, y `remove_index` de sus 4 índices. Alembic reflejaba esas tablas **sin esquema** (`ForeignKey('catalogos.version')`).

- **Causa:** el `search_path` por defecto de PostgreSQL es `"$user", public`, y el usuario de la base se llama `cotizaciones`, igual que el esquema. En cuanto el esquema existe, pasa a ser el esquema por defecto de la sesión. Esto también hacía frágil la ubicación de `alembic_version`, que se crea en `public` la primera vez pero se buscaría primero en `cotizaciones`. Entrada no lo sufre porque su usuario, `partner`, no coincide con ninguno de sus esquemas.
- **Arreglo:** `create_database` fija `-c search_path=public` junto a `statement_timeout`, cubierto en `tests/unitarias/test_database.py`. Con eso: 325 passed, y `alembic_version` en `public` en la base local.

## Pruebas (PostgreSQL real; SQLite no sustituye ninguna)

Cada sesión de pruebas crea `cotizaciones_test_<uuid>`, la migra a head, trunca las tablas entre pruebas y la borra al final. El fixture `catalogo_v1` registra y activa el catálogo de 00 §9.

| Requisito del Paso 30 | Pruebas |
|---|---|
| 1. Migraciones: upgrade desde vacío, downgrade a base, upgrade otra vez; restricciones con nombre | `test_migraciones.py`: `test_migracion_crea_esquemas_y_coincide_con_el_orm` (versión `0001`, `compare_metadata == []`); `test_restricciones_e_indices_con_nombre` (14 restricciones, 5 índices, `indnullsnotdistinct` en `uq_oferta_catalogo`); `test_las_restricciones_rechazan_datos_imposibles` (15 casos que verifican el nombre de la restricción violada); `test_downgrade_a_base_y_upgrade_otra_vez` |
| 2. Repositorios: ida y vuelta exacta de propuesta y rechazo; reconstruir no produce eventos | `test_repositorios.py`: `test_ida_y_vuelta_exacta_de_propuestas_y_rechazos[F1,F2,F3,F5,F6]`, `test_el_importe_conserva_su_valor_entero_exacto` (2^53+1 en BIGINT), `test_columnas_de_la_fila`, `test_catalogo_vigente_ida_y_vuelta_ordenado_por_proveedor`, `test_version_registrada_sin_activar_no_es_vigente`, `test_filas_de_catalogo_invalidas_lanzan_catalogo_invalido`, `test_el_id_de_cada_oferta_es_determinista` |
| 3. Catálogo: script idempotente; código 2 con otro contenido; una sola versión activa; cotización previa conserva su versión | `test_catalogo.py`: `test_el_script_registra_y_activa_de_forma_idempotente`, `test_sin_activar_la_version_queda_registrada_e_inactiva`, `test_misma_version_con_otro_contenido_termina_con_codigo_2`, `test_registrar_la_misma_version_y_huella_no_hace_nada`, `test_activar_una_version_inexistente_falla`, `test_activar_otra_version_deja_una_sola_activa_y_conserva_cotizaciones_previas` (la reentrega de F1 sigue en v1/`a101`; una petición nueva usa v2/`a102`) |
| 4. UoW: fallo al guardar la salida revierte todo; `CatalogoNoDisponible` no deja nada | `test_unidad_trabajo.py`: `test_un_fallo_revierte_cotizacion_inbox_y_salida[inbox,negocio,outbox,commit]` (0/0/0/0 filas y el reintento luego funciona); `test_catalogo_ausente_no_deja_cotizacion_inbox_ni_salida`; `test_catalogo_registrado_sin_activar_equivale_a_catalogo_ausente`; `test_inbox_por_consumidor_con_rollback_y_conflicto`; `test_mismo_comando_con_otra_peticion_es_conflicto_de_mensaje`; `test_sesiones_distintas_y_cierre` |
| 5. Concurrencia con dos hilos y barrera | `test_concurrencia.py` (ver la tabla siguiente) |
| 6. Outbox: reserva vencida; dos despachadores; publicación repetida con el mismo `id_evento` y documento | `test_outbox.py`: `test_reserva_vencida_no_se_confirma_con_el_token_anterior`, `test_dos_despachadores_no_reservan_la_misma_fila`, `test_reintento_publica_el_mismo_id_evento_y_documento`, `test_caida_despues_de_enviar_y_antes_de_marcar_republica_lo_mismo`, `test_despachar_lote_respeta_el_limite_y_devuelve_las_confirmadas`, `test_la_publicacion_ocurre_sin_transaccion_sql_abierta`, `test_destinos_independientes_y_reintento_conserva_identidad`, `test_destinos_desconocidos_solo_bloquean_mientras_estan_pendientes`, `test_la_salida_de_un_resultado_va_a_su_destino` |

### Carreras (dos hilos sincronizados después de leer la petición)

| Caso | Resultado observado | Filas (cotización / inbox / outbox) | Marcas sin efecto |
|---|---|---|---|
| Mismo `command_id` | Una réplica `nueva=True`. La otra espera el commit sobre la clave del inbox, ve la marca y devuelve `(None, nueva=False)` | 1 / 1 / 1 | 0 |
| Distinto `command_id`, misma petición | La segunda choca con `uq_cotizacion_peticion`, `ColisionPersistencia`, reintenta, encuentra la cotización y solo añade su marca; mismo `id_cotizacion` | 1 / 2 / 1 | 0 |
| Datos contradictorios | Un éxito y un `ConflictoPeticion` tras el reintento | 1 / 1 / 1 | 0 |

"Marcas sin efecto" cuenta las marcas de inbox cuya petición no tiene cotización (consulta sobre `documento->'datos'->>'id_peticion'`); debe ser cero.

**Observación:** la rama del handler que la evidencia 03 llamó "defensiva" (la marca ya existe y la cotización no se ve) es en realidad el camino normal de dos réplicas con el mismo `command_id` bajo READ COMMITTED. La segunda leyó antes del commit de la primera y termina sin efecto.

### Pruebas unitarias nuevas

- `tests/unitarias/test_serializacion.py` (30):
  - ida y vuelta exacta de ambos eventos y del comando;
  - documento exacto de la propuesta;
  - rechazo sin precio;
  - importe 2^53+1 exacto;
  - instante normalizado a UTC;
  - formato 2, formato no entero y tipo desconocido fallan; también un documento incompleto y una serialización inválida;
  - lectura del archivo v1: 5 ofertas, sin duración, categoría normalizada, 11 documentos inválidos;
  - la huella no depende del orden ni de la forma de la categoría, y cambia con el contenido o la versión.
- `tests/unitarias/test_rutas.py` (3): constantes de 00 §7, un destino por evento y evento sin ruta.
- `tests/unitarias/test_database.py`: la opción `-c search_path=public`.
- `test_aislamiento.py`: los 15 módulos de persistencia no cargan `pulsar` ni `solicitudes_partner`.

| Archivo | Pruebas |
|---|---|
| `tests/integracion/test_migraciones.py` | 18 |
| `tests/integracion/test_repositorios.py` | 12 |
| `tests/integracion/test_outbox.py` | 9 |
| `tests/integracion/test_unidad_trabajo.py` | 9 |
| `tests/integracion/test_catalogo.py` | 6 |
| `tests/integracion/test_concurrencia.py` | 3 |
| `tests/unitarias/test_serializacion.py` | 30 |
| `tests/unitarias/test_rutas.py` | 3 |

Nuevas: 90 (57 de integración y 33 unitarias). Suite completa: 325.

## Comandos ejecutados y resultado

| Comando | Resultado |
|---|---|
| `docker compose up -d --wait` | `postgres`, `pulsar` y `dev` healthy. Estaban detenidos (exit 255) tras un reinicio de Docker; se reiniciaron con las imágenes locales, sin descargas y conservando los volúmenes |
| `uv run --locked pytest tests -q -s --tb=short` | 325 passed, 1 warning (Starlette/anyio, de terceros) |
| `uv run --locked ruff check .` / `ruff format --check .` | All checks passed / 110 files already formatted (antes de corregir, 1 E501 y 5 archivos por formatear) |
| `uv run --locked mypy src tests scripts migraciones` | Success: no issues found in 95 source files |
| `uv run --locked python scripts/verify_distribution.py` | `Wheel instalado importado fuera del arbol fuente: /tmp/cotizaciones-distribution-xva4rp6g/…/cotizaciones/__init__.py`. Ahora también comprueba `componer_procesamiento_sql`, `crear_uow_cotizaciones`, `DespachadorOutbox` y las 6 tablas en `metadata` |
| `git diff --check` | Sin salida, exit 0 |
| YAML del CI (Ruby, en el host) | `verificacion-unitaria`: 8 pasos; `integracion-postgres`: 5 pasos con servicio `postgres` |

### Recorrido real sobre la base local `cotizaciones` (Compose)

Con `COTIZACIONES_DATABASE_URL=postgresql+psycopg://cotizaciones:…@postgres:5432/cotizaciones`:

| Paso | Resultado |
|---|---|
| `alembic upgrade head` → `alembic current` | `0001 (head)`; `alembic_version` en el esquema `public` |
| `scripts/cargar_catalogo.py --activar` (1.ª vez) | `Catalogo version 1: 5 ofertas, nueva (huella f40d32a5eee9)` · `Version activa: 1` · exit 0 |
| `scripts/cargar_catalogo.py --activar` (2.ª vez) | `… ya existia con la misma huella (huella f40d32a5eee9)` · `Version activa: 1` · exit 0 |
| Handler SQL, F1 (petición `…0021`, comando `…0022`) | `ResultadoProcesamiento(id_cotizacion=4cea0343-…, nueva=True)` |
| El mismo comando otra vez | Mismo `id_cotizacion`, `nueva=False` |
| F5 (petición `…0041`, comando `…0042`, `jardineria`) | `ResultadoProcesamiento(id_cotizacion=5859a1d1-…, nueva=True)` |
| `psql`: `cotizaciones.cotizaciones` | `…0021` PROPUESTA `…a101` 15000000 COP v1 · `…0041` RECHAZADA `SIN_OFERTA_PARA_CATEGORIA` v1 |
| `psql`: `mensajeria.inbox` / `mensajeria.outbox` | 2 marcas (`…0022`, `…0042`) / 2 salidas pendientes: `integracion.cotizacion_registrada.v1` y `integracion.cotizacion_rechazada.v1` |
| `scripts/inspeccionar_outbox.py` | `pendientes: 2`, 0 intentos, sin error ni propietario |

Una fila empresarial y una salida por petición, y ninguna salida adicional por la repetición. Esas dos salidas quedan pendientes en la base local: las publicará el despacho de la Fase 05.

## Decisiones y desviaciones

- **`search_path=public` en todas las conexiones** (ver la prueba roja). No cambia el usuario, el esquema ni ningún contrato.
- **Nombres explícitos para las FK** (`fk_oferta_catalogo`, `fk_cotizacion_catalogo`) y **CHECK en el ORM:** así las restricciones son verificables por nombre. Alembic no compara CHECK; las pruebas sí.
- **`ESPACIO_ENTREGAS` y `ESPACIO_OFERTAS`** son UUID constantes propios de Cotizaciones; no se reutilizó el espacio de Entrada.
- **Integración:** `tests/integracion/datos.py` (utilidades compartidas) y la fábrica `cotizacion_resuelta` en `tests/unitarias/dominio/datos.py` no figuran en el plan; siguen el patrón de Entrada. Tampoco figura `tests/unitarias/test_rutas.py`.
- **Documento del catálogo:** `catalogo_desde_documento` lee solo las claves conocidas. La Fase 08 añadirá `duracion_estimada_minutos`.
- **Códigos de salida de `cargar_catalogo.py`:** 1 si el archivo es inválido (el plan solo fija el código 2).
- **CI `integracion-postgres`:** ejecuta toda la carpeta `tests/integracion`; ningún módulo requiere Pulsar todavía. No se ha ejecutado en GitHub (no hay push); la sintaxis y los comandos se validaron localmente.

## Limitaciones

- Sin Pulsar: no hay consumidor, publicador ni ciclo de despacho; `DespachadorOutbox` solo se probó con transportes falsos.
- Las carreras entre réplicas se probaron con hilos de un mismo proceso sobre PostgreSQL real, no con procesos ni instancias separadas (Fases 05 y 07).
- `connect_timeout` sigue pendiente (evidencia 01, Paso 6).

## Siguiente dependencia

Fase 05 (Pasos 31–42): Records Avro v1 y contratos exportados; mapeadores de mensajería; ciclos supervisados (`EstadoComponente` pasa a `seedwork/infraestructura/ciclos.py`); publicador enrutado por destino; consumidor de peticiones; despacho; lifespan integrado; scripts de Pulsar y dobles etiquetados; integración real con el Pulsar del Compose.
