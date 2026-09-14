# Evidencia 02 — Modelo de dominio

Estado: **Fase 02 terminada** (Pasos 10–16). Fecha: 2026-09-13 (Bogotá). Entorno: contenedor `dev` (Python 3.12.3, uv 0.10.9, aarch64).

## Alcance terminado

El agregado `Cotizacion`, el catálogo y la regla de selección de 00 §8, como código puro, sin SQLAlchemy, psycopg, Pulsar, FastAPI ni Entrada.

| Paso | Archivos | Contenido |
|---|---|---|
| 10 | `seedwork/dominio/{entidades,eventos,objetos_valor,validaciones}.py` | Copiados de Entrada; solo cambian los imports. `Entidad` compara por tipo e ID. `AgregacionRaiz` guarda eventos pendientes y ofrece `retirar_eventos`. Incluye `EventoDominio`, `ObjetoValor` y las validaciones de identidad, instante, versión y texto. No se copió `repositorios.py`. |
| 11 | `dominio/objetos_valor.py` | Enumeraciones `TipoRed`, `TipoSolicitud`, `EstadoCotizacion` y `MotivoRechazo` (propias, no importadas de Entrada). También `normalizar_categoria` (`strip` + `casefold`; vacía → `ValueError`), `Dinero` (entero estricto > 0; moneda `[A-Z]{3}`), `DatosPeticion` (copia canónica de la petición, con propiedad `clave_categoria`) y `OrigenComando`. |
| 12 | `dominio/objetos_valor.py`, `dominio/excepciones.py` | `ErrorCatalogo` → `CatalogoNoDisponible` y `CatalogoInvalido`. `OfertaCatalogo`: categoría normalizada; red general sin partner; homologada con partner. `CatalogoVigente`: versión ≥ 1, tupla no vacía, sin combinaciones (categoría, red, partner, proveedor) repetidas, con `ofertas_de_categoria(clave)`. |
| 13 | `dominio/objetos_valor.py`, `dominio/servicios.py` | `ResultadoCotizacion`: una PROPUESTA lleva solo oferta; un RECHAZO lleva solo motivo. `resolver_oferta(peticion, catalogo)` implementa 00 §8 pasos 1–7. `exigir_catalogo` lanza `CatalogoNoDisponible` y lo reutiliza el agregado. |
| 14 | `dominio/eventos.py` | `CotizacionRegistrada` (proveedor y precio) y `CotizacionRechazada` (motivo), sobre una base común `_ResolucionCotizacion`. Son hechos internos inmutables, no esquemas Avro. |
| 15 | `dominio/entidades.py` | `Cotizacion(AgregacionRaiz)` con sus invariantes (versión de catálogo ≥ 1, `version_cotizacion` = 1, `resuelta_en` con zona, correlación = solicitud, oferta de la misma red, categoría y partner). La fábrica `resolver(...)` recibe IDs e instante inyectados y registra exactamente un evento. Reconstruir con el constructor no registra eventos. |
| 16 | `dominio/repositorios.py`, `tests/unitarias/test_aislamiento.py`, `scripts/verify_distribution.py` | Protocolos `RepositorioCotizaciones` (`obtener_por_peticion`, `guardar`) y `RepositorioCatalogo` (`obtener_vigente`). Prueba de aislamiento del dominio. Imports clave añadidos a la verificación de distribución. |

## Tabla F1–F7 y pruebas que la cubren

Catálogo en memoria: `tests/unitarias/dominio/datos.py::catalogo_laboratorio()`, las cinco ofertas de 00 §9.

| # | Entrada | Resultado esperado | Pruebas |
|---|---|---|---|
| F1 | `plomeria`, GENERAL_HDA, …0002 | PROPUESTA `a101`, 15000000 COP | `test_seleccion.py::test_tabla_de_decisiones[F1]`, `test_cotizacion.py::test_resolver_produce_el_estado_y_un_unico_evento[F1]` |
| F2 | `plomeria`, HOMOLOGADA_PARTNER, …0002 | PROPUESTA `b101`, 18000000 COP | `test_tabla_de_decisiones[F2]`, `test_resolver_produce_…[F2]` |
| F3 | `plomeria`, HOMOLOGADA_PARTNER, …0009 | RECHAZADA `SIN_PROVEEDOR_EN_RED` | `test_tabla_de_decisiones[F3]`, `test_resolver_produce_…[F3]`, `test_homologada_sin_candidato_no_recurre_a_la_red_general` |
| F4 | `electricidad`, HOMOLOGADA_PARTNER, …0002 | RECHAZADA `SIN_PROVEEDOR_EN_RED` | `test_tabla_de_decisiones[F4]`, `test_resolver_produce_…[F4]` |
| F5 | `jardineria`, GENERAL_HDA, …0002 | RECHAZADA `SIN_OFERTA_PARA_CATEGORIA` | `test_tabla_de_decisiones[F5]`, `test_resolver_produce_…[F5]` |
| F6 | `  Plomeria `, GENERAL_HDA, …0002 | PROPUESTA `a101`; conserva la categoría tal como llegó | `test_tabla_de_decisiones[F6]`, `test_cotizacion.py::test_f6_conserva_la_categoria_tal_como_llego`, `test_objetos_valor.py::test_la_peticion_conserva_la_categoria_y_expone_su_clave` |
| F7 | Sin catálogo activo | Error técnico, sin resolución | `test_seleccion.py::test_catalogo_ausente_es_error_tecnico`, `test_cotizacion.py::test_resolver_sin_catalogo_es_error_tecnico`, `test_catalogo.py::test_errores_de_catalogo_son_tecnicos_y_no_errores_de_validacion` |

En el dominio, F7 se demuestra como `CatalogoNoDisponible`: un `RuntimeError`, no un `ValueError` ni un rechazo. Que no quede nada persistido y que el mensaje se reintente se prueba en las fases 03 (rollback con dobles), 04 (PostgreSQL) y 05 (NACK).

Otras reglas de 00 §8 cubiertas:
- El empate `a101`/`a102` elige `a101` aunque sea más caro (`test_empate_elige_el_menor_proveedor_aunque_sea_mas_caro`).
- El resultado no depende del orden del catálogo (`test_la_eleccion_no_depende_del_orden_del_catalogo`).
- En red homologada solo cuentan las ofertas del partner de la petición, aunque otro proveedor ordene antes (`test_homologada_elige_solo_ofertas_del_partner_de_la_peticion`).
- La red general ignora las ofertas homologadas (`test_red_general_ignora_las_ofertas_homologadas`).
- `tipo_solicitud` no interviene (`test_tipo_de_solicitud_no_interviene_en_la_seleccion`).
- El agregado rechaza una propuesta de otro partner, de otra red o de otra categoría (`test_cotizacion.py`).

## Decisiones de la POC (no son reglas literales del negocio)

- **Catálogo sintético:** proveedores, ofertas, importes y partners son datos de laboratorio versionados (D05). Cotizaciones no verifica homologaciones contra terceros.
- **Selección por orden de proveedor:** entre las candidatas se elige la de menor `id_proveedor` en texto canónico. Es un orden estable y reproducible, **no** el "mejor proveedor" ni el "precio de mercado"; la prueba del empate lo demuestra.
- **Una ronda por petición** (`version_cotizacion` = 1, D04).

## Prueba roja

Con las pruebas escritas y sin implementación, `pytest tests/unitarias` falló con **6 errores de recolección**, uno por módulo de prueba del dominio:

```text
E   ModuleNotFoundError: No module named 'cotizaciones.seedwork.dominio.entidades'
E   ModuleNotFoundError: No module named 'cotizaciones.modulos.cotizaciones.dominio.objetos_valor'
E   ModuleNotFoundError: No module named 'cotizaciones.modulos.cotizaciones.dominio.excepciones'
E   ModuleNotFoundError: No module named 'cotizaciones.modulos.cotizaciones.dominio.eventos'
E   ModuleNotFoundError: No module named 'cotizaciones.modulos.cotizaciones.dominio.entidades'
ERROR tests/unitarias/dominio/test_{catalogo,cotizacion,eventos,objetos_valor,seedwork,seleccion}.py
6 errors in 0.19s
```

Con la implementación, la primera corrida dio 211 passed sin fallos de comportamiento. Las correcciones posteriores fueron solo de estilo y tipos en las pruebas: un E501, un B010 de ruff (`setattr` con nombre constante, sustituido por un recorrido de varios campos) y un `comparison-overlap` de mypy (tupla comparada con `()`, sustituida por `len(...) == 0`).

## Pruebas nuevas

| Archivo | Pruebas |
|---|---|
| `tests/unitarias/dominio/test_seedwork.py` | 24 |
| `tests/unitarias/dominio/test_objetos_valor.py` | 54 |
| `tests/unitarias/dominio/test_catalogo.py` | 20 |
| `tests/unitarias/dominio/test_seleccion.py` | 16 |
| `tests/unitarias/dominio/test_eventos.py` | 23 |
| `tests/unitarias/dominio/test_cotizacion.py` | 21 |
| `tests/unitarias/test_aislamiento.py` | +1: `test_dominio_no_carga_sql_http_mensajeria_ni_entrada` (total 4) |

Total nuevas: 159. Suite completa: 211.

## Comandos ejecutados y resultado

En `dev`, salvo `git diff --check`, que se ejecutó en el host:

| Comando | Resultado |
|---|---|
| `uv run --locked pytest tests -q -s --tb=short` | 211 passed, 1 warning (Starlette/anyio, de terceros; ver evidencia 01) |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked ruff format --check .` | 56 files already formatted |
| `uv run --locked mypy src tests scripts` | Success: no issues found in 43 source files |
| `uv run --locked python scripts/verify_distribution.py` | `Wheel instalado importado fuera del arbol fuente: /tmp/cotizaciones-distribution-627xrs_q/environment/lib/python3.12/site-packages/cotizaciones/__init__.py`, que ahora también importa `Cotizacion`, `AgregacionRaiz` y `resolver_oferta` |
| `git diff --check` | Sin salida, exit 0. Solo cubre archivos versionados |

La prueba de aislamiento importa los 10 módulos de dominio (seedwork y módulo) en un `python -I` y afirma que no se cargan `sqlalchemy`, `psycopg`, `pulsar`, `fastapi` ni `solicitudes_partner`.

## Decisiones y desviaciones menores

- **`tests/unitarias/dominio/datos.py`:** no figura en el plan. Contiene el catálogo de 00 §9, los IDs de 00 §10 y fábricas de `DatosPeticion` y `OrigenComando`, compartidos por cinco módulos de prueba (Entrada usa el mismo patrón). El Paso 21 creará su propio `tests/unitarias/aplicacion/datos.py`.
- **`ErrorCatalogo` hereda de `RuntimeError`, no de `ValueError`:** en la Fase 05 un `ValueError` (`ComandoInvalido`, `ConflictoPeticion`) pausa el consumo como mensaje venenoso, mientras que un error de catálogo debe producir NACK y reintento. Hay una prueba que lo fija.
- **Diferencias de espacios en la categoría:** `DatosPeticion` compara la categoría **tal como llegó**, así que `"plomeria"` y `" plomeria"` son peticiones distintas. Si la misma `id_peticion` llega con otra forma, será un conflicto en la Fase 03, aunque ambas resuelvan a la misma clave. Es consecuencia directa de "copia canónica campo a campo" (Paso 11) y queda fijado en `test_peticiones_difieren_si_cambia_cualquier_campo[categoria1]`.
- **`EstadoCiclo` y `EstadoComponente`:** siguen en `infraestructura/ciclo_vida.py` hasta el Paso 34 (ver evidencia 01).

## Limitaciones

- No hay durabilidad, caso de uso, inbox, outbox ni mensajería: el dominio solo decide y registra el hecho interno.
- `OfertaCatalogo` todavía no tiene `duracion_estimada_minutos`; llega en la Fase 08 (E3).

## Siguiente dependencia

Fase 03 (Pasos 17–21): el caso de uso `ProcesarPeticionHandler`, que no crea duplicados (idempotente), probado con dobles en memoria (UoW transaccional, reloj e identificadores deterministas). Necesita el seedwork de aplicación (`reintentar_colision`, `Publicacion`, `UnidadTrabajo` sin `preparar_entrada`) y `ConflictoMensaje`.
