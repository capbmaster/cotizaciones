# 00 — Contratos, datos de laboratorio y configuración

Fuente: `planes-otros-microservicios/01-contratos-y-datos.md`. Aquí se fijan los detalles que ese documento deja abiertos (nombres de record, orden de campos, normalización, catálogo, IDs y variables). Cualquier cambio posterior de un contrato público requiere avisar al usuario y a los consumidores antes de continuar.

## 1. Tópicos y suscripciones

Prefijo de todos los tópicos: `persistent://public/default/`. Tipo de suscripción: Shared en todas. Clave de partición de cada mensaje: `id_trabajo`.

| Tópico | Contrato | Rol de Cotizaciones | Suscripciones sobre el tópico |
|---|---|---|---|
| `solicitar-cotizacion-v1` | SolicitarCotizacion.v1 | Consumidor | `cotizaciones-peticiones-v1` (propia) |
| `cotizacion-registrada-v1` | CotizacionRegistrada.v1 (revisiones 1 y 2) | Productor | `orquestacion-cotizacion-registrada-v1`, `seguimiento-cotizacion-registrada`, `e3-historico-01` … `e3-historico-05` |
| `cotizacion-rechazada-v1` | CotizacionRechazada.v1 | Productor | `orquestacion-cotizacion-rechazada-v1`, `seguimiento-cotizacion-rechazada-v1` |

Cotizaciones publica cada resultado **una sola vez**; cada suscripción recibe su copia. Las réplicas de Cotizaciones comparten `cotizaciones-peticiones-v1`. Cerrar un consumidor nunca elimina su suscripción (no usar `unsubscribe`).

## 2. Reglas comunes de los mensajes

- Serialización Avro binaria con esquema registrado en Pulsar. Record **sin namespace**, campos en el orden listado, todos obligatorios salvo indicación. El `.avsc` exportado debe ser idéntico a lo que produce el SDK para la clase Record (se prueba).
- UUID como texto canónico en minúsculas con guiones. Instantes como texto ISO 8601 en UTC con desplazamiento `+00:00` (misma forma que Entrada).
- Propiedades de cada mensaje: `event_id` (o `command_id`) y `tipo`. El `MessageId` del broker nunca sustituye al ID lógico.
- Un tipo de registro por tópico. No existe un envelope genérico con payload arbitrario.
- `tipo` y `version_contrato` son independientes: el sufijo `.v1` del tipo nombra la familia compatible; `version_contrato` es la revisión del esquema.

## 3. SolicitarCotizacion.v1 — lector provisional (propietario: Orquestación)

Record Avro: `SolicitarCotizacionV1`.

| # | Campo | Tipo Avro | Regla de validación en Cotizaciones |
|---|---|---|---|
| 1 | `command_id` | string | UUID no nulo |
| 2 | `tipo` | string | Exactamente `SolicitarCotizacion.v1` |
| 3 | `version_contrato` | int | ≥ 1 (hoy 1); no exigir igualdad estricta |
| 4 | `instante` | string | ISO 8601 con zona horaria |
| 5 | `correlacion` | string | UUID igual a `id_solicitud` |
| 6 | `causacion` | string | UUID (event_id del evento de Entrada) |
| 7 | `id_peticion` | string | UUID no nulo; clave empresarial |
| 8 | `id_trabajo` | string | UUID no nulo |
| 9 | `id_solicitud` | string | UUID no nulo |
| 10 | `id_partner` | string | UUID no nulo |
| 11 | `categoria` | string | Texto con al menos un carácter visible |
| 12 | `tipo_solicitud` | string | `SINIESTRO` o `INSTALACION` |
| 13 | `tipo_red` | string | `GENERAL_HDA` o `HOMOLOGADA_PARTNER` |
| 14 | `id_politica` | string | UUID no nulo |
| 15 | `version_politica` | int | > 0 |

Si alguna regla falla, el mensaje es **inválido**: no se hace ACK ni NACK, se pausa el bucle de consumo y readiness lo informa (ver Paso 34). Nunca se convierte en un rechazo empresarial.

## 4. CotizacionRegistrada.v1 (propietario: Cotizaciones)

Record Avro: `CotizacionRegistradaV1` en ambas revisiones (mismo nombre, mismo tópico, mismo `tipo`).

| # | Campo | Tipo Avro | Contenido |
|---|---|---|---|
| 1 | `event_id` | string | UUID del hecho; estable en todos los reintentos |
| 2 | `tipo` | string | `CotizacionRegistrada.v1` |
| 3 | `version_contrato` | int | 1 (revisión 1) o 2 (revisión 2) |
| 4 | `instante` | string | Instante de la resolución |
| 5 | `correlacion` | string | Copia de `correlacion` del comando |
| 6 | `causacion` | string | `command_id` del comando que creó la cotización |
| 7 | `id_peticion` | string | De la petición |
| 8 | `id_trabajo` | string | De la petición |
| 9 | `id_solicitud` | string | De la petición |
| 10 | `id_partner` | string | De la petición |
| 11 | `version_catalogo` | int | Versión activa usada al resolver |
| 12 | `version_cotizacion` | int | Siempre 1 en esta POC |
| 13 | `id_cotizacion` | string | ID del agregado |
| 14 | `id_proveedor` | string | Proveedor sintético elegido |
| 15 | `importe_menor` | long | > 0, unidades menores enteras |
| 16 | `moneda` | string | `COP` en el laboratorio |
| 17 | `categoria` | string | Tal como llegó en la petición (sin normalizar) |
| 18 | `tipo_red` | string | De la petición |
| 19 | `duracion_estimada_minutos` | union `null`/`int`, **default null** | **Solo revisión 2** (fase E3). Positivo o null; null = desconocido, nunca 0 |

## 5. CotizacionRechazada.v1 (propietario: Cotizaciones)

Record Avro: `CotizacionRechazadaV1`. Revisión única 1; no cambia en E3.

Campos 1–12 idénticos a los de la tabla anterior (con `tipo` = `CotizacionRechazada.v1`), seguidos de:

| # | Campo | Tipo Avro | Contenido |
|---|---|---|---|
| 13 | `motivo` | string | `SIN_OFERTA_PARA_CATEGORIA` o `SIN_PROVEEDOR_EN_RED` |

Sin proveedor, importe ni `id_cotizacion`.

## 6. Semántica del resultado

- Una petición (`id_peticion`) produce como máximo una cotización y un evento de resultado, para siempre. Una petición repetida (mismo o distinto `command_id`) con los mismos datos de negocio no crea otra cotización ni otro evento.
- Misma `id_peticion` con datos de negocio distintos (trabajo, solicitud, partner, categoría, tipo de solicitud, red, política) es un **conflicto**: no se escribe nada y el mensaje se trata como inválido.
- Catálogo activo ausente: error técnico recuperable (NACK con demora), sin cotización, sin inbox y sin evento.
- Dinero: `importe_menor` en unidades menores con escala 2 para COP. COP 150.000,00 se representa como 15000000. Prohibido usar float.
- Reintentar una publicación reenvía el mismo `event_id`, contenido e instante, leídos del outbox; nunca se consulta el catálogo al reenviar.

## 7. Nombres internos

| Concepto | Valor |
|---|---|
| Consumidor inbox del caso de uso | `cotizaciones.procesar_peticion` |
| Destino outbox de la propuesta | `integracion.cotizacion_registrada.v1` |
| Destino outbox del rechazo | `integracion.cotizacion_rechazada.v1` |
| Evento de dominio interno → destino | `CotizacionRegistrada` → propuesta; `CotizacionRechazada` → rechazo |

## 8. Regla de selección de oferta (decisión de la POC, no regla literal de negocio)

Clave de categoría: el texto de `categoria` sin espacios al inicio/fin y en minúsculas (`casefold`). Se aplica igual al cargar el catálogo y al buscar.

1. Si no existe catálogo activo → error técnico `CatalogoNoDisponible`.
2. Ofertas de la categoría = ofertas del catálogo activo cuya clave de categoría coincide.
3. Si no hay ninguna → RECHAZADA con `SIN_OFERTA_PARA_CATEGORIA`.
4. Candidatas: si la red es `GENERAL_HDA`, ofertas de red general (sin partner); si es `HOMOLOGADA_PARTNER`, ofertas de red homologada cuyo `id_partner` es el de la petición. Nunca se recurre a la red general como alternativa.
5. Si no hay candidatas → RECHAZADA con `SIN_PROVEEDOR_EN_RED`.
6. Elegida = candidata con el menor `id_proveedor` en su forma de texto canónica → PROPUESTA con su proveedor, importe y moneda (y en la revisión 2, su duración). No se llama "mejor proveedor" ni "precio de mercado".
7. `tipo_solicitud` no interviene en la selección; solo se conserva.

## 9. Catálogo sintético de laboratorio

Partner de laboratorio: `00000000-0000-0000-0000-000000000002` (el mismo que usa Entrada por defecto). Partner sin proveedores homologados: `00000000-0000-0000-0000-000000000009`. Moneda: COP en todas las ofertas.

| Proveedor | Categoría | Red | Partner | Importe menor | Duración en v2 |
|---|---|---|---|---|---|
| `00000000-0000-0000-0000-00000000a101` | plomeria | GENERAL_HDA | — | 15000000 | 30 |
| `00000000-0000-0000-0000-00000000a102` | plomeria | GENERAL_HDA | — | 12000000 | 30 |
| `00000000-0000-0000-0000-00000000b101` | plomeria | HOMOLOGADA_PARTNER | …0002 | 18000000 | 30 |
| `00000000-0000-0000-0000-00000000a201` | electricidad | GENERAL_HDA | — | 20000000 | null |
| `00000000-0000-0000-0000-00000000a301` | cerrajeria | GENERAL_HDA | — | 9000000 | 90 |

`a102` es más barato que `a101`, pero se elige `a101` por el orden estable: la prueba demuestra que la regla no optimiza precio. Formato del archivo de datos `datos/catalogos/catalogo-vN.json`: objeto con `version` (entero positivo) y `ofertas` (lista de objetos con `id_proveedor`, `categoria`, `tipo_red`, `id_partner` o null, `importe_menor`, `moneda`). El archivo v2 añade `duracion_estimada_minutos` (entero positivo o null) a cada oferta; el archivo v1 no contiene esa clave.

### Resultados esperados (fixtures comunes)

| # | Categoría recibida | Red | Partner | Resultado esperado |
|---|---|---|---|---|
| F1 | `plomeria` | GENERAL_HDA | …0002 | PROPUESTA `a101`, 15000000 COP |
| F2 | `plomeria` | HOMOLOGADA_PARTNER | …0002 | PROPUESTA `b101`, 18000000 COP |
| F3 | `plomeria` | HOMOLOGADA_PARTNER | …0009 | RECHAZADA `SIN_PROVEEDOR_EN_RED` |
| F4 | `electricidad` | HOMOLOGADA_PARTNER | …0002 | RECHAZADA `SIN_PROVEEDOR_EN_RED` |
| F5 | `jardineria` | GENERAL_HDA | …0002 | RECHAZADA `SIN_OFERTA_PARA_CATEGORIA` |
| F6 | `  Plomeria ` | GENERAL_HDA | …0002 | PROPUESTA `a101`; se publica `categoria` tal como llegó |
| F7 | cualquiera, sin catálogo activo | — | — | Error técnico; nada persistido; reintento |
| F8 (v2) | `plomeria` / `cerrajeria` / `electricidad` | GENERAL_HDA | …0002 | Duración 30 / 90 / null; filtro de Seguimiento ≤ 60 incluye solo la de 30 |

## 10. IDs de los ejemplos públicos

Los archivos `docs/contratos/*.ejemplo.json` usan IDs fijos para que las pruebas comparen bytes: `id_solicitud`/`correlacion` `…0001`, `id_partner` `…0002`, `id_politica` `…0003`, `causacion` del comando `…000f` (event_id del ejemplo de Entrada), `id_trabajo` `…0020`, `id_peticion` `…0021`, `command_id` `…0022`, `id_cotizacion` `…0030`, `event_id` de la propuesta `…0031`, `event_id` del rechazo `…0032` (categoría `jardineria`). Instante del comando `2026-09-12T15:00:03+00:00`; instante del resultado `2026-09-12T15:00:04+00:00`. `…00NN` abrevia `00000000-0000-0000-0000-0000000000NN`.

## 11. Configuración por variables de entorno

| Variable | Predeterminado | Uso |
|---|---|---|
| `COTIZACIONES_SERVICE_NAME` | `cotizaciones` | Nombre devuelto por health |
| `COTIZACIONES_DATABASE_URL` | vacío (sin base ni procesamiento) | Debe usar `postgresql+psycopg://` |
| `COTIZACIONES_DB_POOL_SIZE` / `COTIZACIONES_DB_MAX_OVERFLOW` | 5 / 5 | Pool por instancia (E4: conexiones totales crecen con réplicas) |
| `COTIZACIONES_DB_STATEMENT_TIMEOUT_MS` | 3000 | Límite por sentencia, compatible con cierre < 10 s |
| `COTIZACIONES_PULSAR_URL` | `pulsar://127.0.0.1:6650` | Broker |
| `COTIZACIONES_PULSAR_ADMIN_URL` | `http://127.0.0.1:18086` | Solo scripts de preparación y métricas |
| `COTIZACIONES_TOPICO_PETICIONES` | `persistent://public/default/solicitar-cotizacion-v1` | Tópico consumido |
| `COTIZACIONES_SUSCRIPCION_PETICIONES` | `cotizaciones-peticiones-v1` | Suscripción propia |
| `COTIZACIONES_TOPICO_REGISTRADA` | `persistent://public/default/cotizacion-registrada-v1` | Publicación de propuestas |
| `COTIZACIONES_TOPICO_RECHAZADA` | `persistent://public/default/cotizacion-rechazada-v1` | Publicación de rechazos |
| `COTIZACIONES_PULSAR_TIMEOUT_SEGUNDOS` | 3 | Conexión, operación y envío |
| `COTIZACIONES_PULSAR_RECEPTOR_COLA` | 1 | Tamaño de cola de recepción (reparto justo entre réplicas) |
| `COTIZACIONES_PULSAR_DEMORA_NACK_MS` | 5000 | Reentrega tras error técnico |
| `COTIZACIONES_RETARDO_LABORATORIO_MS` | 0 | Solo calibración E4; si es > 0 se registra como sintético |
| `COTIZACIONES_POSTGRES_PORT` | 55436 | Solo Compose local |
| `COTIZACIONES_TEST_DATABASE_URL` | `postgresql+psycopg://cotizaciones:cotizaciones_local@127.0.0.1:55436/cotizaciones` | Pruebas de integración |
| `COTIZACIONES_TEST_PULSAR_URL` / `COTIZACIONES_TEST_PULSAR_ADMIN_URL` | `pulsar://127.0.0.1:6650` / `http://127.0.0.1:18086` | Pruebas de integración |
| `PORT` | 8002 en local | Puerto HTTP (Cloud Run lo inyecta) |

Validaciones de `Settings` al construirse: tres tópicos distintos y con prefijo `persistent://`; suscripción no vacía; pool, timeouts y cola positivos; retardo ≥ 0.

## 12. Artefactos que Cotizaciones entrega

| Destinatario | Artefactos |
|---|---|
| Orquestación | `solicitar-cotizacion-v1.avsc` (propuesta lectora para que la adopte idéntica), resultados v1 (`.avsc`, ejemplos, checksums SHA-256), reglas semánticas de las secciones 3–6 |
| Seguimiento | Resultados v1 y revisión 2 de la propuesta, fixtures binarios, IDs de las peticiones E3 (F8) |
