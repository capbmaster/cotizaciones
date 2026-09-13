# Fase 06 — Consultas HTTP (Pasos 43–46)

Corresponde a `planes-otros-microservicios/cotizaciones/06-consultas-cotizaciones.md`. HTTP síncrono solo para **consultas** (excepción permitida por la rúbrica). Separación comando/consulta sobre el estado relacional propio: no se crea una segunda base, un proyector ni un tópico CQRS para mostrar una oferta ya persistida. Requiere haber cerrado la Fase 05.

---

## Paso 43 — Consultas en la capa de aplicación

**Archivos:** `modulos/cotizaciones/aplicacion/consultas.py`, `modulos/cotizaciones/aplicacion/handlers/consultar_cotizaciones.py`, `tests/unitarias/aplicacion/test_consultas.py`.

**Contenido de `consultas.py`:**
- `VistaCotizacion` (DTO inmutable, serializable por FastAPI; nunca el agregado): `id_cotizacion`, `id_peticion`, `id_trabajo`, `id_solicitud`, `id_partner`, `categoria`, `tipo_solicitud`, `tipo_red`, `estado`, `id_proveedor`, `importe_menor` y `moneda` (nulos en rechazo), `motivo` (nulo en propuesta), `version_catalogo`, `version_cotizacion`, `id_comando_origen` y `resuelta_en`. El Paso 56 añade `duracion_estimada_minutos`.
- `FiltroCotizaciones`: `id_peticion`, `id_trabajo` y `estado`, todos opcionales y combinados con Y.
- Protocolo `RepositorioLecturaCotizaciones`: `obtener(id_cotizacion)` y `listar(filtro, limite, desplazamiento)`.

**Handlers:** `ConsultarCotizacionHandler` devuelve la vista o nada. `ListarCotizacionesHandler` valida `limite` entre 1 y 100 y `desplazamiento` ≥ 0 (si no, `ValueError`) y devuelve una lista.

**Pruebas:** con un repositorio en memoria, filtro exacto por petición, combinación de filtros y límites inválidos.

## Paso 44 — Repositorio de lectura SQL

**Archivo:** `modulos/cotizaciones/infraestructura/repositorios.py` (ampliación).

`RepositorioLecturaCotizacionesSQL` recibe la fábrica de sesiones y abre una sesión propia por llamada. Selecciona columnas de `cotizaciones.cotizaciones` directamente hacia `VistaCotizacion`, sin reconstruir el agregado. Orden estable: `resuelta_en` y luego `id`. Nunca consulta tablas ni APIs de otro servicio.

## Paso 45 — Endpoints

**Archivos:** `src/cotizaciones/api/cotizaciones.py`, `api/app.py` (incluir el router), `config/bootstrap.py` (`componer_consulta(base)` y `componer_listado(base)`).

| Método y ruta | Parámetros | Respuestas |
|---|---|---|
| `GET /cotizaciones/{id_cotizacion}` | UUID en la ruta | 200 `VistaCotizacion`; 404 "cotizacion no encontrada"; 422 UUID inválido; 503 sin base |
| `GET /cotizaciones` | `id_peticion`, `id_trabajo` (UUID opcionales), `estado` (enumeración opcional), `limite` (1–100, por defecto 20), `desplazamiento` (≥ 0, por defecto 0) | 200 lista (posiblemente vacía); 422 parámetros inválidos; 503 sin base |

Reglas: funciones de endpoint síncronas (FastAPI las ejecuta fuera del event loop). La base se obtiene de `app.state` con una dependencia que responde 503 si no existe (igual que Entrada). No hay encabezado de partner: es una consulta operativa interna del laboratorio. Un 404 significa "no hay resolución confirmada": una petición que sigue en Pulsar no se presenta como resolución, y su pendiente lo muestra Orquestación.

## Paso 46 — Contrato de consulta, pruebas y evidencia

**Archivos:** `docs/contratos/consultas.md`, `docs/contratos/openapi.json`, `tests/api/test_cotizaciones.py`, `tests/contratos/test_openapi.py`, `tests/integracion/test_consultas_http.py`, README (sección de consultas), `docs/evidencias/06-consultas.md`.

**Contenido:**
- `consultas.md`: endpoints, campos, significado de cada código y diferencia entre recepción del comando, resultado confirmado y publicación a Orquestación.
- `openapi.json`: exportado desde `create_app(Settings()).openapi()`. La prueba de contrato compara el archivo con la salida actual.

**Pruebas:**
1. API con handlers sustituidos por dependencias: 200, 404, 422 por límites y 503 sin base.
2. Integración con PostgreSQL y Pulsar reales: el productor doble (Paso 39) envía F1 y F5, el servicio arranca con lifespan, se espera con plazo la fila, y luego `GET` por ID y listado por `id_peticion` devuelven propuesta con importe y rechazo con motivo y sin precio.
3. Tras cerrar y volver a abrir la app sobre la misma base, las consultas devuelven los mismos datos.

**Verificación:** verificación estándar. La evidencia 06 incluye un recorrido real comando → persistencia → consulta HTTP con los IDs usados. Postman o curl sirven para la demo, pero no sustituyen las pruebas transaccionales.
