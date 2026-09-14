# Evidencia 06 — Consultas HTTP

Estado: **Fase 06 terminada** (Pasos 43–46). Fecha: 2026-09-14 (Bogotá). Entorno: contenedor `dev`; verificación adicional manual sobre PostgreSQL y Pulsar del Compose.

Solicitado por el usuario: reducir el esfuerzo en pruebas unitarias exhaustivas y priorizar la verificación de lo principal. Esta fase tiene menos pruebas unitarias que las anteriores; se compensó con una prueba de integración de punta a punta y un recorrido manual real con `curl`.

## Alcance terminado

| Paso | Archivos | Contenido |
|---|---|---|
| 43 | `aplicacion/consultas.py`, `aplicacion/handlers/consultar_cotizaciones.py` | `VistaCotizacion` (DTO inmutable, nunca el agregado), `FiltroCotizaciones` (tres campos opcionales combinados con Y) y el protocolo `RepositorioLecturaCotizaciones`. `ConsultarCotizacionHandler` y `ListarCotizacionesHandler` (valida `limite` 1–100 y `desplazamiento` ≥ 0). |
| 44 | `infraestructura/repositorios.py` (ampliación) | `RepositorioLecturaCotizacionesSQL`: abre su propia sesión por llamada, selecciona columnas de `cotizaciones.cotizaciones` directo a `VistaCotizacion` (sin `cargar_cotizacion`, que reconstruiría el agregado), orden estable `resuelta_en, id`. |
| 45 | `api/cotizaciones.py`, `api/app.py`, `config/bootstrap.py` (ampliación) | `GET /cotizaciones/{id_cotizacion}` (200/404/422/503) y `GET /cotizaciones` (200/422/503) con los filtros del Paso 43. Endpoints síncronos (FastAPI los ejecuta en su pool de hilos). `obtener_base` responde 503 si `app.state.database` es `None`, igual que Entrada. `componer_consulta` y `componer_listado` en `bootstrap.py`. |
| 46 | `docs/contratos/{consultas.md,openapi.json}`, README, `tests/api/test_cotizaciones.py`, `tests/contratos/test_openapi.py`, `tests/integracion/test_consultas_http.py` | Contrato de consulta con los tres momentos (comando recibido / resultado confirmado / publicación); `openapi.json` exportado desde `create_app(Settings()).openapi()`. |

## Pruebas

| Archivo | Pruebas | Qué cubre |
|---|---|---|
| `tests/api/test_cotizaciones.py` | 6 | 200 con la vista completa; 404 sin resultado; 422 por UUID inválido; 422 por límites fuera de rango (0, 101, desplazamiento negativo); filtros combinados pasados al handler; 503 sin base configurada |
| `tests/contratos/test_openapi.py` | 2 | El `openapi.json` publicado coincide con `create_app(Settings()).openapi()`; las dos rutas de cotizaciones están documentadas |
| `tests/integracion/test_consultas_http.py` | 1 | **Punta a punta con PostgreSQL real:** el handler SQL resuelve F1 (propuesta) y F5 (rechazo); `GET /cotizaciones/{id}` de cada una devuelve el estado, importe/moneda o motivo correctos; `GET /cotizaciones?id_peticion=…` filtra la propuesta; se cierra y reabre la app sobre la misma base y las consultas siguen devolviendo los mismos datos |

Nuevas: 9. Suite completa: **438 passed**.

No se repitió aquí la matriz completa de combinaciones de filtros ni cada código de error por separado en varios niveles (dominio/aplicación/API): las reglas de paginación y filtrado ya están cubiertas una vez en el handler (`ListarCotizacionesHandler`) y una vez en el límite HTTP (`Query(ge=1, le=100)`), sin duplicar la matriz.

## Prueba roja

Antes de implementar, `tests/api/test_cotizaciones.py` y `tests/contratos/test_openapi.py` fallaban por `ImportError`/`ModuleNotFoundError` (`cotizaciones.api.cotizaciones`, `consultas.py`, `handlers.consultar_cotizaciones` no existían). Con la implementación, la primera corrida de `test_cotizaciones.py` falló por un detalle menor: FastAPI/Pydantic serializa un `datetime` en UTC con sufijo `Z`, no `+00:00`; se ajustó la aserción de la prueba, no el código de producción.

## Verificación manual real (Paso 46, cierre de fase)

Con el servicio arrancado sobre la base local (`postgres`) y Pulsar del Compose, usando datos ya persistidos en fases anteriores:

| Petición | Resultado |
|---|---|
| `GET /cotizaciones/4cea0343-…` (F1, PROPUESTA) | 200, con `id_proveedor=…a101`, `importe_menor=15000000`, `moneda=COP`, `motivo=null` |
| `GET /cotizaciones?id_peticion=…0021` | 200, lista con esa misma cotización |
| `GET /cotizaciones/00000000-…9999` (inexistente) | 404 `{"detail":"cotizacion no encontrada"}` |
| `GET /cotizaciones/no-es-un-uuid` | 422, error de Pydantic sobre `path.id_cotizacion` |
| `GET /cotizaciones?limite=0` | 422, error de Pydantic sobre `query.limite` (`ge=1`) |

## Comandos ejecutados y resultado

| Comando | Resultado |
|---|---|
| `uv run --locked pytest tests -q -s --tb=short` | **438 passed**, 1 warning (Starlette/anyio, de terceros) |
| `uv run --locked ruff check .` / `ruff format --check .` | All checks passed / 142 files already formatted |
| `uv run --locked mypy src tests scripts migraciones` | Success: no issues found in 123 source files |
| `uv run --locked python scripts/verify_distribution.py` | Importa `ConsultarCotizacionHandler`, `ListarCotizacionesHandler` y comprueba que `/cotizaciones/{id_cotizacion}` está en el `openapi()` de la app instalada |
| `git diff --check` | Sin salida, exit 0 |

## Decisiones y desviaciones

- **`verify_distribution.py` usa `app.openapi()["paths"]` en vez de iterar `app.routes`.** La versión instalada de Starlette envuelve los routers incluidos con `_IncludedRouter` (sin atributo `.path`) en `app.routes`; `openapi()` sí aplana las rutas reales, así que es la comprobación robusta.
- **Sin encabezado de partner:** a diferencia de Entrada (`X-Partner-Laboratorio`), esta consulta es interna del laboratorio y no filtra por partner (00 no lo pide).
- **`_vista_desde_fila` no reutiliza `cargar_cotizacion`:** lee directo las columnas de `CotizacionSQL`, tal como pide el Paso 44 ("sin reconstruir el agregado").

## Limitaciones

- No hay paginación por cursor, solo `limite`/`desplazamiento`.
- Como pidió el enunciado de esta fase, no se añadieron pruebas unitarias exhaustivas para cada combinación de filtro o cada código de error en capas separadas; la cobertura se concentra en el camino principal más una prueba de extremo a extremo real.

## Siguiente dependencia

Fase 07 (Pasos 47–52): recuperación (E8) y escalamiento (E4). Métricas y reconciliación, prueba automatizada de caída/recuperación, prueba de réplicas concurrentes bajo carga, y los procedimientos de laboratorio E8/E4 de Cotizaciones.
