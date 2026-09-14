# Evidencia 03 — Caso de uso idempotente

Estado: **Fase 03 terminada** (Pasos 17–21). Fecha: 2026-09-13 (Bogotá). Entorno: contenedor `dev` (Python 3.12.3, uv 0.10.9, aarch64).

**No hay durabilidad ni consumo autónomo.** El handler se probó solo con dobles en memoria. PostgreSQL (inbox, outbox, restricciones UNIQUE) llega en la Fase 04, y el consumidor de Pulsar con ACK/NACK en la Fase 05.

## Alcance terminado

| Paso | Archivos | Contenido |
|---|---|---|
| 17 | `seedwork/aplicacion/{identificadores,reloj,reintentos,unidad_trabajo,publicacion}.py`, `seedwork/infraestructura/{reloj,identificadores}.py`, `seedwork/aplicacion/excepciones.py` | Copiados de Entrada: los puertos `GeneradorIdentificadores` y `Reloj`, `reintentar_colision` (3 intentos solo ante `ColisionPersistencia`), `Publicacion`/`Publicador`, y los adaptadores `RelojActual` (UTC) e `IdentificadoresAleatorios` (uuid4). El protocolo `UnidadTrabajo` conserva el context manager, `confirmar`, `revertir` y `registrar_salida`, **sin `preparar_entrada`**. Se añade `ConflictoMensaje(ValueError)`. |
| 18 | `aplicacion/comandos.py`, `aplicacion/excepciones.py` | `ProcesarPeticionCotizacion(origen, datos)`: inmutable; rechaza cualquier cosa que no sea `OrigenComando` y `DatosPeticion`, así que nunca transporta un Record Avro ni una Session. `ConflictoPeticion(ValueError)`. |
| 19 | `aplicacion/unidad_trabajo.py` | `UnidadTrabajoCotizaciones(UnidadTrabajo, Protocol)` con `cotizaciones`, `catalogos` y `registrar_recepcion(consumidor, comando) -> bool`. Devuelve verdadero si la marca es nueva y falso si ya existía igual; lanza `ConflictoMensaje` si existía con otro contenido. |
| 20 | `aplicacion/handlers/procesar_peticion.py`, `config/bootstrap.py` | `ProcesarPeticionHandler` (consumidor `cotizaciones.procesar_peticion`, decorado con `reintentar_colision`) y `ResultadoProcesamiento(id_cotizacion, nueva)`. `componer_procesamiento(crear_unidad, reloj, identificadores)`, sin clases fábrica. |
| 21 | `tests/unitarias/aplicacion/{datos,test_procesar_peticion,test_reintentos}.py`, `tests/unitarias/aplicacion/dobles/{reloj,identificadores,repositorios,unidad_trabajo}.py` | Dobles deterministas y una UoW en memoria **transaccional**, con ganchos de fallo y de colisión. |

El handler sigue el pseudocódigo del Paso 20:
1. Busca la cotización por `id_peticion`.
2. Si existe:
   - con otros datos de negocio → `ConflictoPeticion`;
   - con los mismos datos → solo añade la marca de inbox (confirma si es nueva) y devuelve la resolución original con `nueva=False`.
3. Si no existe:
   - si la marca ya estaba (caso defensivo) → termina sin efecto;
   - si no, **recién ahí lee el catálogo**, resuelve con IDs e instante inyectados, guarda, pasa cada evento retirado a `registrar_salida` y confirma.

No publica, no hace ACK y no conoce Pulsar.

## Dobles

- **Reloj e identificadores:**
  - `RelojFijo` devuelve siempre el instante del resultado de 00 §10;
  - `IdentificadoresSecuenciales` entrega `UUID(int=100)` para la cotización y `101` para su evento.
- **Repositorios en memoria:** `RepositorioCotizacionesMemoria` imita la UNIQUE `uq_cotizacion_peticion` lanzando `ColisionPersistencia`. `RepositorioCatalogoMemoria` avisa de cada consulta.
- **`UnidadTrabajoMemoria`:** trabaja sobre una copia profunda del estado confirmado. `confirmar()` la publica en el `AlmacenMemoria`; `revertir()` o salir por excepción la descartan. El almacén expone lo confirmado (cotizaciones, recepciones, salidas) y estos contadores y ganchos:
  - `aperturas`, `confirmaciones` y `consultas_catalogo`;
  - `fallar_al_guardar` y `fallar_al_registrar_salida`;
  - `colision_con`: en el primer `guardar`, confirma en el almacén lo que "otra réplica" resolvió para la misma petición y lanza `ColisionPersistencia`.

## Pruebas del plan (Paso 21) y dónde están

Todas en `tests/unitarias/aplicacion/test_procesar_peticion.py`:

| # | Requisito del plan | Prueba |
|---|---|---|
| 1 | F1–F5: una cotización, una marca y una salida del tipo correcto | `test_peticion_nueva_deja_una_cotizacion_una_marca_y_una_salida[F1…F5]` |
| 2 | Catálogo ausente: `CatalogoNoDisponible` y nada escrito | `test_catalogo_ausente_no_deja_cotizacion_inbox_ni_salida_y_se_puede_reintentar`, que además comprueba que tras cargar el catálogo la reentrega se procesa |
| 3 | Fallo al registrar la salida: sin cotización ni marca | `test_fallo_al_registrar_la_salida_no_deja_cotizacion_ni_marca` y `test_fallo_al_guardar_la_cotizacion_no_deja_marca_ni_salida` |
| 4 | Rechazo válido: confirma inbox y salida | `test_rechazo_valido_confirma_inbox_y_salida` |
| 5 | El mismo comando dos veces: `nueva=False` y sin otra salida | `test_el_mismo_comando_dos_veces_no_crea_otra_salida` (1 confirmación, 1 lectura del catálogo) |
| 6 | Otro `command_id` con los mismos datos: dos marcas, una salida, mismo ID | `test_otro_comando_con_los_mismos_datos_solo_agrega_su_marca` |
| 7 | Cambio de catálogo entre entregas: resolución original | `test_cambio_de_catalogo_entre_entregas_devuelve_la_resolucion_original` (sigue `a101`, catálogo v1) |
| 8 | Misma `id_peticion` con otra categoría o red: `ConflictoPeticion` y nada escrito | `test_misma_peticion_con_otros_datos_es_conflicto_y_no_escribe[otra-categoria, otra-red, otro-trabajo]` |
| 9 | `ColisionPersistencia` en el primer intento: reutiliza la cotización existente | `test_colision_en_el_primer_intento_reutiliza_la_cotizacion_de_la_otra_replica` (2 aperturas, 1 cotización, 2 marcas, la salida de la otra réplica) |

Pruebas adicionales:
- `test_mismo_comando_con_otra_peticion_es_conflicto_de_mensaje` (`ConflictoMensaje`, sin leer el catálogo);
- `test_marca_sin_cotizacion_termina_sin_efecto_ni_lectura_de_catalogo` (rama defensiva);
- `test_el_comando_propio_solo_admite_tipos_de_dominio`;
- `test_los_conflictos_son_errores_de_validacion` (en la Fase 05 un `ValueError` pausa el consumo);
- `test_el_consumidor_del_inbox_tiene_el_nombre_del_contrato`;
- `test_reintentos.py`: 3 pruebas del decorador (3 intentos ante colisión, 1 ante otro error, y una colisión transitoria que se supera en el segundo intento).

Pruebas nuevas: 24 (21 + 3). Suite completa: 235.

## Prueba roja

Con pruebas y dobles escritos y sin implementación, `pytest tests/unitarias` falló en la recolección:

```text
E   ModuleNotFoundError: No module named 'cotizaciones.config.bootstrap'
E   ModuleNotFoundError: No module named 'cotizaciones.seedwork.aplicacion.reintentos'
ERROR tests/unitarias/aplicacion/test_procesar_peticion.py
ERROR tests/unitarias/aplicacion/test_reintentos.py
2 errors in 0.59s
```

Con la implementación, la primera corrida dio 235 passed sin fallos de comportamiento. La única corrección fue de formato en `aplicacion/comandos.py`.

## Comandos ejecutados y resultado

En `dev`, salvo `git diff --check`, que se ejecutó en el host:

| Comando | Resultado |
|---|---|
| `uv run --locked pytest tests -q -s --tb=short` | 235 passed, 1 warning (Starlette/anyio, de terceros; ver evidencia 01) |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked ruff format --check .` | 81 files already formatted (antes de corregir, 1 archivo) |
| `uv run --locked mypy src tests scripts` | Success: no issues found in 67 source files |
| `uv run --locked python scripts/verify_distribution.py` | `Wheel instalado importado fuera del arbol fuente: /tmp/cotizaciones-distribution-5igineai/environment/lib/python3.12/site-packages/cotizaciones/__init__.py`, que también importa `componer_procesamiento` y `ProcesarPeticionHandler` |
| `git diff --check` | Sin salida, exit 0 |

La prueba de aislamiento (`test_dominio_y_aplicacion_no_cargan_sql_http_mensajeria_ni_entrada`) ahora cubre 23 módulos: dominio, seedwork de aplicación, `RelojActual`, `IdentificadoresAleatorios`, la capa de aplicación del módulo y `config/bootstrap.py`. Ninguno carga `sqlalchemy`, `psycopg`, `pulsar`, `fastapi` ni `solicitudes_partner`.

## Decisiones y desviaciones menores

- **`tests/unitarias/aplicacion/datos.py`** solo define `comando_peticion(...)` y reutiliza `datos_peticion`, `origen_comando` y el catálogo de `tests/unitarias/dominio/datos.py`, en vez de duplicarlos. El plan pedía ahí "las fábricas y el catálogo"; el resultado es el mismo, con una sola fuente.
- **`test_reintentos.py`** no figura en el plan: prueba el decorador copiado de Entrada, como hace Entrada.
- **La colisión se simula en `guardar`**, que es donde PostgreSQL la detectará (flush con `uq_cotizacion_peticion`). En la Fase 04 la UoW SQL convertirá esa violación UNIQUE en `ColisionPersistencia`.
- **Categoría con otros espacios:** sigue vigente la observación de la evidencia 02. Una reentrega de la misma `id_peticion` con `" plomeria"` en vez de `"plomeria"` es `ConflictoPeticion`.

## Limitaciones

- Sin PostgreSQL, sin inbox ni outbox reales y sin consumo de Pulsar. Las carreras entre réplicas solo se simularon con el gancho de colisión; la Fase 04 las prueba con hilos y PostgreSQL real.
- `Publicacion` y `Publicador` se copiaron, pero no se usan hasta el despacho del outbox (Fases 04–05).

## Siguiente dependencia

Fase 04 (Pasos 22–30):
- PostgreSQL local (Compose ya levantado en `127.0.0.1:55436`), Alembic y la migración `0001_cotizaciones.py`;
- seedwork SQL (inbox, outbox con reservas, `UnidadTrabajoSQL`), ORM, mapeadores, serialización, repositorios SQL y `UnidadTrabajoCotizacionesSQL`;
- carga de catálogo y pruebas de integración con carreras reales.
