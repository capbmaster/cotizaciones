# Congelación de v1 (Paso 53)

Fecha: 2026-09-14 (Bogotá). Commit congelado: `6cf211a` (tag anotado `cotizaciones-v1.0.0`, local, sin push). `esquemas/v1/eventos.py` no se modifica desde aquí; la revisión 2 vive en `esquemas/v2/eventos.py` (Paso 55).

## SHA-256

| Artefacto | Valor | Cómo se obtuvo |
|---|---|---|
| `cotizacion-registrada-v1.avsc` | `74c8c2b09ea08d93f8ba7a6a29d5c5cf25738ed9d9d881b6ee6c8db97a6fbe5c` | Ya publicado en [CHECKSUMS.sha256](CHECKSUMS.sha256) (Fase 05) |
| `cotizacion-rechazada-v1.avsc` | `1f4907dbbdddfc4026e1d8e4855cca91838b5731b1c015efa3ad4aab34f589b5` | Ídem |
| `solicitar-cotizacion-v1.avsc` | `26826ee852fe8ea2f261257f7857b5db4ec5cc65a79eab63de442b600ccea054` | Ídem |
| `fixtures/cotizacion-registrada-v1.bin` | `8ebaef2a7f894aa9d1563f056da4807853fedbcd62c3e9b1430836c587dffa00` | Bytes Avro del ejemplo F1, exportados con `AvroSchema(CotizacionRegistradaV1).encode(...)` sobre el documento serializado de la Fase 05 |
| Wheel `cotizaciones-0.1.0-py3-none-any.whl` | `a07e15af6229ef3d916d3f857bcf8e420dfc7a889fdca1e9cce5cff794837fc1` | `uv build` sobre el commit congelado, `sha256sum` sobre el `.whl` |
| Imagen `cotizaciones:v1` (linux/amd64) | `sha256:41910a3185e7cc7c642c549c5ad4c1b569d3fb8f1c76754491473c8b5404acd8` | `docker build --platform linux/amd64 -t cotizaciones:v1 .`, `docker inspect --format '{{.Id}}'`. Imagen local, no publicada a un registro (sin `RepoDigests` de un remoto) |

## Verificación del laboratorio de imagen (Pasos 60-61, adelantados)

Ejecutado con `docker-compose.imagen.yaml` (stack aislado, PostgreSQL y Pulsar propios, sin relación con el `docker-compose.yaml` de desarrollo):

| Verificación | Resultado |
|---|---|
| `preparacion` (migra, carga/activa catálogo v1, prepara Pulsar) | Exit code 0; 5 suscripciones creadas, retención 60min/100MB y cuota de backlog aplicadas en los 3 tópicos |
| `cotizaciones` arranca sano | `/health/live` 200, `/health/ready` 200 `listo` con ambos componentes `OPERANDO` |
| `smoke` (`scripts/smoke_despliegue.py`) | `SMOKE OK`, exit 0: F1 → PROPUESTA `a101`; F5 → RECHAZADA `SIN_OFERTA_PARA_CATEGORIA` |
| `docker compose stop -t 10 cotizaciones` | Cierre ordenado en **1 s** (`Shutting down` → `Application shutdown complete` → `Finished server process`), muy por debajo del plazo |
| Reinicio (`docker compose start cotizaciones`) | `/health/ready` 200 de inmediato; las 2 cotizaciones sembradas por el smoke siguen en la base (`SELECT count(*)` antes y después = 2) |

## Nota de plataforma: emulación QEMU en Apple Silicon

El cliente nativo (C++) de `pulsar-client` aborta el proceso (`terminate called without an active exception`) al cerrarse normalmente cuando corre bajo emulación QEMU `linux/amd64` sobre Apple Silicon — reproducido tanto en un script independiente como en uno anidado. **No ocurre en Cloud Run**, que ejecuta `amd64` nativo. Mientras tanto, `scripts/smoke_despliegue.py` evita el problema terminando con `os._exit()` en vez de dejar que el intérprete finalice normalmente (lo que evita el destructor del cliente). Documentado en el propio script.

También se observó una corrupción del almacenamiento de BookKeeper en una corrida descartada del laboratorio de imagen (`ManagedLedgerException: Error while recovering ledger`), resuelta recreando los volúmenes del stack aislado (`docker compose -f docker-compose.imagen.yaml down -v`). No es un problema del código: es un artefacto de un Pulsar standalone desechable en un entorno de laboratorio.
