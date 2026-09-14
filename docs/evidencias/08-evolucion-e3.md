# Fase 08 — Evolución E3: `duracion_estimada_minutos` (Pasos 53–59)

Fecha: 2026-09-14 (Bogotá). Commit base congelado (v1): `6cf211a` (tag anotado
`cotizaciones-v1.0.0`, local, sin push — ver [Paso 53](../contratos/CONGELACION-v1.md)). El trabajo
de esta fase (Pasos 54–59) queda sobre `d93fa5b` en la rama `main`, pendiente de commit hasta
autorización explícita del usuario.

## Resumen por paso

| Paso | Entregable | Estado |
|---|---|---|
| 53 | Congelación v1, tag, imagen `cotizaciones:v1`, fixture y checksums | Cerrado (ver [CONGELACION-v1.md](../contratos/CONGELACION-v1.md)) |
| 54 | Migración `0002_duracion_estimada`, dominio, ORM, serialización aditiva | Implementado y verificado |
| 55 | Record v2 (`esquemas/v2/eventos.py`), fixtures y `.avsc`/`.ejemplo.json` rev2 | Implementado y verificado |
| 56 | Escritor v2 (`mensaje_registrada`), `catalogo-v2.json`, consulta con duración | Implementado y verificado (F8) |
| 57 | `--compatibilidad FULL_TRANSITIVE`, pruebas de compatibilidad, job de CI | Implementado y verificado |
| 58 | `docs/experimentos/e3-cotizaciones.md` (participación por brazo) | Cerrado |
| 59 | Este documento | Cerrado |

Verificación final de la fase: `pytest tests -q` → **488 passed**; `ruff check .` y
`ruff format --check .` limpios; `mypy src tests scripts migraciones` → *Success: no issues found
in 134 source files*; `python scripts/verify_distribution.py` → instala el wheel construido en un
entorno limpio e importa fuera del árbol fuente sin error; `git diff --check` sin advertencias.

## Esquemas entregados a Seguimiento

| Artefacto | SHA-256 |
|---|---|
| `docs/contratos/cotizacion-registrada-v1.avsc` (v1, congelado) | `74c8c2b09ea08d93f8ba7a6a29d5c5cf25738ed9d9d881b6ee6c8db97a6fbe5c` |
| `docs/contratos/cotizacion-registrada-v1.rev2.avsc` (revisión 2) | `abf26aba642102bc86bfe09a3221ff5de12739448a80acaefb4c3b1677e8ba7b` |
| `docs/contratos/cotizacion-registrada-v1.ejemplo.json` (v1) | `50c1dabd5c83c1ec6c4e748253484900ce8e2bf0b5cb96fc65739738fe7fc499` |
| `docs/contratos/cotizacion-registrada-v1.rev2.ejemplo.json` (rev2) | `eb36d80a51a6e83bee83d06e1ea8027a0018be6d24d96e985c4f82e2b574424a` |
| `docs/contratos/fixtures/cotizacion-registrada-v1.bin` (v1, bytes Avro) | `8ebaef2a7f894aa9d1563f056da4807853fedbcd62c3e9b1430836c587dffa00` |
| `docs/contratos/fixtures/cotizacion-registrada-v1.rev2.bin` (rev2, bytes Avro) | `0e1226ac3105e6c8c6a056fc28289d766c1ac1f6ee4b658831278ebebd136b9b` |

Todos los valores están también en [`docs/contratos/CHECKSUMS.sha256`](../contratos/CHECKSUMS.sha256)
y se verifican en cada corrida de pruebas
(`tests/contratos/test_resultados.py::test_los_checksums_publicados_coinciden_con_los_archivos`).

Los campos 1–18 de la revisión 2 son idénticos a v1, mismo `name` de Record
(`CotizacionRegistradaV1`, sin namespace) y mismo `tipo` (`CotizacionRegistrada.v1`); el único
campo añadido es el 19, `duracion_estimada_minutos`, unión `["null", "int"]` con `default: null` —
verificado byte a byte contra lo que emite el SDK real en
`tests/contratos/test_resultados_rev2.py::test_rev2_difiere_de_rev1_solo_en_el_campo_anadido_con_default_null`.
`CotizacionRechazadaV1` no cambia en esta fase.

## Imagen y artefactos (heredados del Paso 53)

| Artefacto | SHA-256 |
|---|---|
| Wheel `cotizaciones-0.1.0-py3-none-any.whl` | `a07e15af6229ef3d916d3f857bcf8e420dfc7a889fdca1e9cce5cff794837fc1` |
| Imagen `cotizaciones:v1` (linux/amd64) | `sha256:41910a3185e7cc7c642c549c5ad4c1b569d3fb8f1c76754491473c8b5404acd8` |

Esta imagen corresponde al escritor v1 congelado, previo a los Pasos 54–56. La imagen que publica
el escritor v2 se construirá en la Fase 09 (Paso 60 en adelante) sobre el commit que incluya esta
fase; no se ha vuelto a construir una imagen `cotizaciones:v2` en el alcance de este documento.

## IDs de las peticiones F8

Ver el detalle completo en [`docs/experimentos/e3-cotizaciones.md`](../experimentos/e3-cotizaciones.md#f8-peticiones-de-referencia-para-seguimiento).
Resumen:

| id_peticion | Categoría | Duración esperada |
|---|---|---:|
| `00000000-0000-0000-0000-0000000000a0` | plomeria | 30 |
| `00000000-0000-0000-0000-0000000000a1` | cerrajeria | 90 |
| `00000000-0000-0000-0000-0000000000a2` | electricidad | null |
| `00000000-0000-0000-0000-000000000021` (F1, histórica, resuelta con v1 antes del cambio) | plomeria | null (conservada; nunca se republica) |

Reproducible con
`tests/integracion/test_catalogo.py::test_f8_catalogo_v2_real_publica_duraciones_30_90_null`, que
activa el `datos/catalogos/catalogo-v2.json` real (no un catálogo sintético de prueba) y verifica
tanto el resultado de dominio como los bytes que produciría el escritor real (`mensaje_registrada`)
para cada caso.

## Qué es doble y qué es real

- **Real, en este repositorio:** el escritor de Cotizaciones (dominio, persistencia, serialización,
  mapeo a Avro), la migración de base de datos, el broker Pulsar real usado por
  `tests/integracion/*` y por `tests/integracion/test_compatibilidad_broker.py` (arranca con
  `docker compose up -d --wait pulsar` o, en CI, `apachepulsar/pulsar:4.1.3` standalone).
- **Doble, todavía:** no existe un consumidor real de Orquestación ni de Seguimiento en este punto
  del curso — ambos servicios no están implementados como código desplegable. Todo lo que en este
  documento se llama "lector v1" o "lector v2" de esos servicios es, en el alcance de Cotizaciones,
  un consumidor de prueba con el esquema correspondiente
  (`tests/integracion/test_compatibilidad_broker.py::test_lector_v1_congelado_sigue_consumiendo_mensajes_v2`),
  no el servicio real de Seguimiento. Las suscripciones `orquestacion-cotizacion-registrada-v1` y
  `seguimiento-cotizacion-registrada` que crea `scripts/preparar_pulsar.py` existen para que esos
  servicios, cuando existan, tengan su cursor ya posicionado desde `Earliest`; hoy nadie las
  consume salvo los dobles de laboratorio (`enviar_peticion.py`/`consumir_resultados.py`) descritos
  en `docs/despliegue` y en los guiones de Fase 07.
- Esta limitación ya se había comunicado explícitamente durante la sesión de trabajo: con lo que
  existe hoy en el curso, no hay integración real posible entre Cotizaciones y Orquestación o
  Seguimiento, solo integración por dobles. Este documento no cambia esa situación; solo dispone el
  contrato (esquemas, fixtures, catálogo v2, compatibilidad de broker) para cuando esos servicios
  existan.

## Límite de rollback

Una vez que un hecho `CotizacionRegistrada` se archivó en `mensajeria.eventos` y se envió por el
outbox con el escritor v2, **no existe una ruta de código para volver a publicarlo con el
mapeador v1**: desde el Paso 56, `mensaje_registrada` en `mapeadores_eventos.py` construye
siempre el Record v2 (`CotizacionRegistradaV1` de `esquemas/v2/eventos.py`,
`version_contrato = 2`), incluso para documentos históricos de formato 1 (los publica con
`duracion_estimada_minutos = null`, pero seguimos usando el escritor v2). Volver a la imagen
`cotizaciones:v1` detiene la generación de *nuevos* hechos v2 (los siguientes que se archiven usan
el mapeador v1 otra vez), pero no reescribe ni retransmite los que el escritor v2 ya envió. Esto es
consistente con la regla general de la fase: nunca se republican hechos históricos con un
`version_contrato` distinto del que tenían cuando ocurrieron.

## Verificación de compatibilidad (Paso 57)

Confirmado contra un broker Pulsar real (no solo con fastavro):

1. Un tópico de control en `FULL_TRANSITIVE` acepta el Record v2 tras tener registrado el v1, y
   **rechaza** (`IncompatibleSchema`) tanto retipar `importe_menor` a `string` como añadir un campo
   obligatorio sin default.
2. Un consumidor suscrito con el esquema v1 congelado lee sin error un mensaje publicado con el
   escritor v2, ignorando el campo nuevo.
3. Sin red, con `fastavro.schemaless_reader` y los dos fixtures binarios: escritor v1 → lector v2
   da duración nula; escritor v2 → lector v1 ignora el campo.

Job de CI dedicado: `compatibilidad` en `.github/workflows/ci.yml`, que ejecuta solo
`tests/contratos/test_compatibilidad.py` y `tests/integracion/test_compatibilidad_broker.py` contra
un Pulsar standalone recién levantado, con `time` sobre el paso de pytest (objetivo < 60 s; medido
localmente en ~0.2 s de ejecución de pruebas, sin contar el arranque del broker).
