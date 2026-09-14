# E3 — Evolución de esquema: `duracion_estimada_minutos`

Seguimiento lidera el experimento (su lector es quien demuestra los seis brazos); Cotizaciones es
dueño del escritor y del dato. La revisión 2 (`esquemas/v2/eventos.py`) añade un único campo
opcional al **mismo** tópico, con el **mismo** nombre de Record (`CotizacionRegistradaV1`, sin
namespace) y el **mismo** `tipo` (`CotizacionRegistrada.v1`). El contrato de rechazo
(`CotizacionRechazadaV1`) no cambia en ningún brazo.

## Participación de Cotizaciones por brazo

| Brazo | Qué hace Cotizaciones | Estado en este servicio |
|---|---|---|
| 1. Referencia | Escritor v1 activo; genera ofertas por el recorrido normal, sin `duracion_estimada_minutos` en el documento persistido | Recorrido normal previo al Paso 54, verificado en toda la Fase 05–07 |
| 2. Productor primero | Aplica la migración `0002_duracion_estimada` y luego cambia el binario al escritor v2, con los lectores antiguos (v1 congelado) intactos | Implementado (Pasos 54–56); ejecutado localmente contra `catalogo-v2.json` en `test_f8_catalogo_v2_real_publica_duraciones_30_90_null` |
| 3. Consumidor primero | Mantiene el escritor v1 mientras el lector v2 de Seguimiento se despliega; solo después cambia al escritor v2 | El binario lo decide quien despliega Cotizaciones (imagen `v1` vs `v2` sobre la misma base migrada); no requiere cambios de código adicionales a los del brazo 2 |
| 4. Histórico | Cotizaciones no hace nada: el lector v2 de Seguimiento debe leer los hechos v1 ya retenidos en el tópico y no republica nada | Verificado del lado de Cotizaciones: `test_f8_...` reenvía la petición F1 (resuelta con v1, antes del cambio) y comprueba que el documento archivado en `mensajeria.eventos` no cambia y que `ResultadoProcesamiento.nueva` es `False` en la reentrega |
| 5. Reversión | Drenar el outbox de propuestas (`inspeccionar_outbox.py` en 0 pendientes), registrar el punto y volver a la imagen v1 sobre la base ya migrada; las ofertas nuevas salen sin duración (el escritor v1 nunca la incluye) y las ya resueltas conservan la suya en la base de datos | Compatible por diseño: la migración es aditiva y nunca se revierte; solo cambia el binario. No ejecutado como corrida de despliegue real en este servicio (ver Límites) |
| 6. Control incompatible | Prueba 2 del Paso 57: un tópico de control aislado en `FULL_TRANSITIVE` acepta v2 y rechaza un cambio incompatible | Implementado y verificado en `tests/integracion/test_compatibilidad_broker.py::test_full_transitive_acepta_v2_y_rechaza_cambios_incompatibles` |

## F8: peticiones de referencia para Seguimiento

Tres peticiones de laboratorio, resueltas **después** de activar `datos/catalogos/catalogo-v2.json`,
cubren los tres resultados de duración de 00 §9:

| id_peticion (`uuid_lab`) | Categoría | Proveedor | Duración esperada |
|---|---|---|---:|
| `00000000-0000-0000-0000-0000000000a0` | plomeria | a101/a102 (según orden de resolución) | 30 |
| `00000000-0000-0000-0000-0000000000a1` | cerrajeria | a301 | 90 |
| `00000000-0000-0000-0000-0000000000a2` | electricidad | a201 | null |

El filtro de Seguimiento "≤ 60 minutos" (00 §9) debe incluir solo la primera de las tres. La
petición histórica F1 (`ID_PETICION = uuid_lab("0021")`), resuelta **antes** de activar v2, se
reenvía en la misma prueba para demostrar el brazo 4: conserva `duracion_estimada_minutos = null`
y no genera un segundo hecho. Reproducible con
`tests/integracion/test_catalogo.py::test_f8_catalogo_v2_real_publica_duraciones_30_90_null`.

## Medidas de Cotizaciones

- **Esfuerzo real:** implementación de los Pasos 54–57 (migración, Record v2, escritor v2,
  compatibilidad de broker) en una sesión de trabajo asistida, muy por debajo del objetivo de
  ≤ 2 días-persona del plan.
- **Cero hechos históricos republicados:** verificado en `test_f8_...` comparando el documento
  archivado en `mensajeria.eventos` antes y después de reenviar la petición F1 — es
  byte-a-byte idéntico, y `ResultadoProcesamiento.nueva` es `False` en la reentrega.
- **Duración del job de compatibilidad:** las pruebas de `tests/contratos/test_compatibilidad.py`
  y `tests/integracion/test_compatibilidad_broker.py` completan en ~0.2 s localmente (excluyendo
  el arranque de Pulsar); el job dedicado `compatibilidad` en `.github/workflows/ci.yml` mide su
  propia duración con `time` y tiene el objetivo de 60 s del Paso 57.

## Límites

- Los brazos 2, 4 y 6 están verificados con pruebas automatizadas reales (PostgreSQL y, para el 6,
  un broker Pulsar real) dentro de este repositorio. Los brazos 3 y 5 dependen de una secuencia de
  despliegue (dos versiones de imagen desplegadas en orden) que **no se ha ejecutado** como corrida
  real: en la fecha de este documento, Orquestación y Seguimiento no existen todavía como servicios
  desplegables, así que no hay lector real con el que coordinar el corte de brazo 3, ni un entorno
  de despliegue en el que demostrar el brazo 5 con imágenes `v1`/`v2` reales. Ver también
  `docs/evidencias/08-evolucion-e3.md` para el detalle de qué es doble y qué es real.
- El rollback tiene un límite estructural, no solo operativo: una vez que un hecho se archivó y se
  envió con el escritor v2 (`version_contrato = 2`), **no existe** una ruta para volver a
  publicarlo con el mapeador v1 — `mensaje_registrada` en la revisión actual del código solo
  produce Records v2 (Paso 56). Revertir el binario a la imagen v1 detiene la emisión de nuevos
  hechos v2, pero no reescribe los ya publicados.
