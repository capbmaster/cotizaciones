# Contratos de mensajería de Cotizaciones

Serialización: Avro binario con el esquema registrado en Pulsar, **records sin namespace** y campos en el orden de los `.avsc`. Los `.ejemplo.json` ilustran el contenido con los IDs fijos de [00 §10](../plans/00-contratos-y-datos.md); no son el formato enviado. Los consumidores solo necesitan estos archivos: no importan clases, tablas ni el paquete Python del productor.

| Contrato | Record | Tópico | Propietario | Rol de Cotizaciones | Archivos |
|---|---|---|---|---|---|
| `SolicitarCotizacion.v1` | `SolicitarCotizacionV1` | `persistent://public/default/solicitar-cotizacion-v1` | **Orquestación** | Consumidor (suscripción `cotizaciones-peticiones-v1`) | [avsc](solicitar-cotizacion-v1.avsc), [ejemplo](solicitar-cotizacion-v1.ejemplo.json) |
| `CotizacionRegistrada.v1` (revisión 1) | `CotizacionRegistradaV1` | `persistent://public/default/cotizacion-registrada-v1` | Cotizaciones | Productor | [avsc](cotizacion-registrada-v1.avsc), [ejemplo](cotizacion-registrada-v1.ejemplo.json) |
| `CotizacionRechazada.v1` | `CotizacionRechazadaV1` | `persistent://public/default/cotizacion-rechazada-v1` | Cotizaciones | Productor | [avsc](cotizacion-rechazada-v1.avsc), [ejemplo](cotizacion-rechazada-v1.ejemplo.json) |

[CHECKSUMS.sha256](CHECKSUMS.sha256) contiene el SHA-256 de cada `.avsc` y ejemplo; `tests/contratos` lo verifica.

## `SolicitarCotizacion.v1`: propuesta lectora pendiente de adopción

**El contrato pertenece a Orquestación, que todavía no lo publica.** Este `.avsc` es la copia lectora provisional de Cotizaciones y se entrega para que Orquestación lo adopte **idéntico**: mismo nombre de record, mismo orden y mismos tipos. Un nombre u orden distintos producen un esquema incompatible en el tópico. Mientras tanto se usa el productor `scripts/enviar_peticion.py`, rotulado "DOBLE DE ORQUESTACION".

**Clasificación: comando distribuido.** Pide una acción al propietario de las cotizaciones y puede fallar; todavía no representa un hecho.

Propiedades del mensaje: `command_id` y `tipo`. Clave de partición: `id_trabajo`.

Reglas que valida Cotizaciones:

| Campo | Regla |
|---|---|
| `command_id` | UUID no nulo; identidad del mensaje en el inbox |
| `tipo` | Exactamente `SolicitarCotizacion.v1` |
| `version_contrato` | Mayor o igual que 1, sin exigir igualdad estricta |
| `instante` | ISO 8601 con zona horaria |
| `correlacion` | Igual a `id_solicitud` |
| `causacion` | UUID (el `event_id` del evento de Entrada) |
| `id_peticion` | UUID no nulo; clave empresarial (una cotización por petición) |
| `id_trabajo`, `id_solicitud`, `id_partner`, `id_politica` | UUID no nulos |
| `categoria` | Al menos un carácter visible; se conserva tal como llegó |
| `tipo_solicitud` | `SINIESTRO` o `INSTALACION` (no interviene en la selección) |
| `tipo_red` | `GENERAL_HDA` o `HOMOLOGADA_PARTNER` |
| `version_politica` | Mayor que 0 |

**Mensaje inválido o contradictorio:** Cotizaciones no hace ACK ni NACK. Pausa su consumo y `/health/ready` informa el ID y el motivo. Nunca lo convierte en un rechazo empresarial.

**Misma `id_peticion` con otros datos de negocio:** es un conflicto y no se escribe nada.

**Petición repetida** (mismo o distinto `command_id`, con los mismos datos): no crea otra cotización ni otro evento.

**Catálogo ausente:** error técnico. Se hace NACK con demora y el mensaje se reintenta.

## `CotizacionRegistrada.v1` y `CotizacionRechazada.v1`

**Clasificación: eventos de integración.** Informan una resolución confirmada y llevan la carga necesaria para el efecto aguas abajo. Nadie debe llamar por HTTP al productor para completarlos.

Cada resultado se publica **una sola vez** en su tópico, y cada suscripción recibe su copia:

| Tópico | Suscripciones |
|---|---|
| `cotizacion-registrada-v1` | `orquestacion-cotizacion-registrada-v1`, `seguimiento-cotizacion-registrada` y, en E3, `e3-historico-01` a `05` |
| `cotizacion-rechazada-v1` | `orquestacion-cotizacion-rechazada-v1`, `seguimiento-cotizacion-rechazada-v1` |

Las réplicas de un mismo consumidor comparten su suscripción (tipo Shared); no hay orden global.

Contenido de los mensajes:
- **Propiedades:** `event_id` y `tipo`.
- **Clave de partición:** `id_trabajo`.
- **`causacion`:** el `command_id` que creó la cotización.
- **`correlacion`:** el `id_solicitud`.
- **`version_contrato`:** revisión del esquema (1). Es independiente del sufijo `.v1` de `tipo`, que nombra la familia compatible. Los lectores no deben exigir igualdad estricta, porque la revisión 2 de la propuesta (E3) añadirá `duracion_estimada_minutos` opcional en el mismo tópico.
- **Dinero:** `importe_menor` es long en unidades menores con escala 2 (COP 150.000,00 = 15000000).
- **`categoria`** de la propuesta: se publica tal como llegó en la petición.
- **El rechazo** lleva `motivo` (`SIN_OFERTA_PARA_CATEGORIA` o `SIN_PROVEEDOR_EN_RED`) y no lleva proveedor, importe ni `id_cotizacion`.

La entrega es **al menos una vez**. Un reintento reenvía el mismo `event_id`, contenido e instante, leídos del outbox; nunca se vuelve a consultar el catálogo. El consumidor deduplica por `event_id` antes del ACK.

## Preparación local

Desde el contenedor `dev`. Registra los esquemas y crea la suscripción propia y las de Orquestación y Seguimiento antes del tráfico. Con `--admin-url` aplica, por tópico, cuota de backlog (50 MiB y 30 min, `producer_exception`) y retención (60 min y 100 MiB), y las lee de vuelta:

```bash
docker compose exec dev uv run --locked python scripts/preparar_pulsar.py --admin-url http://pulsar:8080
```

Pulsar 4.1 exige configurar la cuota **antes** que la retención, y que la retención la supere; si no, responde HTTP 412. El script nunca reinicia cursores ni anula suscripciones. Estos valores bastan para el laboratorio local; para E8/E4 hay que dimensionarlos según tasa × duración.

Dobles de desarrollo, no son servicios reales:
- `scripts/enviar_peticion.py` (**DOBLE DE ORQUESTACION**): envía comandos. Admite `--repetir-comando`, `--nuevo-comando-misma-peticion` y `--contradictoria`, y `--salida` escribe un JSONL con los IDs enviados.
- `scripts/consumir_resultados.py` (**DOBLE LECTOR v1**): lee con estos `.avsc`, persiste en SQLite por `event_id`, detecta contradicciones y hace ACK después del commit. `--interrumpir-tras-commit` termina con código 75 antes del ACK.

Versiones probadas juntas: Python 3.12.3, `pulsar-client[avro]` 3.13.0, fastavro 1.12.2 y broker 4.1.3.
