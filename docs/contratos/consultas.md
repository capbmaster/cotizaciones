# Consultas HTTP de Cotizaciones

HTTP se usa **solo para consultas** (excepción de la rúbrica para operaciones de lectura). Comandos y resultados siguen viajando por Pulsar. Las consultas leen directamente el estado relacional propio (`cotizaciones.cotizaciones`); no hay una segunda base, un proyector ni un tópico CQRS.

Esquema exportado: [openapi.json](openapi.json), generado desde `create_app(Settings()).openapi()`.

## Tres momentos distintos de una petición

| Momento | Dónde se ve | Qué significa |
|---|---|---|
| Comando recibido | Nada visible por HTTP | Pulsar entregó el mensaje; puede seguir en proceso o en el inbox |
| Resultado confirmado | `GET /cotizaciones/{id}` o `GET /cotizaciones` | La transacción de PROPUESTA/RECHAZADA ya se confirmó en PostgreSQL |
| Publicación a Orquestación | Fuera de este servicio | El evento salió del outbox hacia `cotizacion-registrada-v1` o `cotizacion-rechazada-v1` |

Una petición que todavía está en Pulsar (procesándose o pausada) **no aparece** en estas consultas: un 404 no distingue "no existe" de "todavía no se resolvió". Orquestación es quien conoce sus propios pendientes.

## `GET /cotizaciones/{id_cotizacion}`

| Código | Cuándo |
|---|---|
| 200 | Existe una cotización con ese ID; devuelve `VistaCotizacion` |
| 404 | No hay una resolución confirmada con ese ID |
| 422 | `id_cotizacion` no es un UUID |
| 503 | La base de datos no está configurada en esta instancia |

## `GET /cotizaciones`

Parámetros, todos opcionales y combinados con Y:

| Parámetro | Tipo | Regla |
|---|---|---|
| `id_peticion` | UUID | — |
| `id_trabajo` | UUID | — |
| `estado` | `PROPUESTA` \| `RECHAZADA` | — |
| `limite` | entero | 1–100, por defecto 20 |
| `desplazamiento` | entero | ≥ 0, por defecto 0 |

Orden estable: `resuelta_en` y luego `id`. Responde 200 con una lista (vacía si no hay coincidencias) o 422 si algún parámetro es inválido.

## `VistaCotizacion`

DTO de solo lectura; nunca el agregado de dominio.

| Campo | Presente en |
|---|---|
| `id_cotizacion`, `id_peticion`, `id_trabajo`, `id_solicitud`, `id_partner` | Siempre |
| `categoria`, `tipo_solicitud`, `tipo_red` | Siempre (de la petición original) |
| `estado` | Siempre (`PROPUESTA` o `RECHAZADA`) |
| `id_proveedor`, `importe_menor`, `moneda` | Solo en `PROPUESTA`; `null` en `RECHAZADA` |
| `motivo` | Solo en `RECHAZADA`; `null` en `PROPUESTA` |
| `version_catalogo`, `version_cotizacion` | Siempre |
| `id_comando_origen` | Siempre (el `command_id` que produjo esta resolución) |
| `resuelta_en` | Siempre (instante del dominio, no el de inserción) |

Sin encabezado de partner: es una consulta operativa interna del laboratorio, no una API de cara al partner.
