# E8 — Recepción durante caída de Cotizaciones

Artefacto evaluado: **Entrada de Solicitudes de Partner**. Servicio que falla: **Cotizaciones**. El resto del sistema (Entrada, PostgreSQL de Entrada, Pulsar, Orquestación cuando exista) sigue activo durante toda la caída. Este documento es el procedimiento de laboratorio; la corrida grupal con los cuatro servicios se anexa aparte (ver `docs/evidencias/07-recuperacion-y-escala.md` para lo ya ejecutado a nivel de Cotizaciones sola).

## Preparación

1. Migrar la base de Cotizaciones a `head` (`alembic upgrade head`) y cargar/activar el catálogo v1 (`scripts/cargar_catalogo.py --activar`).
2. Preparar tópicos y suscripciones con `scripts/preparar_pulsar.py --admin-url <admin>`, **antes** de generar tráfico. Nunca crear una suscripción nueva ni reiniciar cursores durante la corrida.
3. Dimensionar backlog y retención del tópico `solicitar-cotizacion-v1` para al menos 5 minutos de caída: `--backlog-mib`/`--backlog-minutos` deben cubrir `tasa_estimada × 5 min` con margen; `--retencion-mib`/`--retencion-minutos` deben superar esa cuota (el script ya valida `retencion > backlog`).
4. Verificar en las estadísticas de administración (`GET .../stats`) que la suscripción `cotizaciones-peticiones-v1` tiene **cero consumidores** antes de empezar a contar la caída — así se confirma que no queda una instancia previa compitiendo por el mismo tráfico.

## Línea base (2 minutos)

Con Cotizaciones arriba (`docker compose up -d --wait` completo, o el Service de Cloud Run en escala 1), ejecutar el recorrido completo: Entrada admite una solicitud → Orquestación (o el doble `scripts/enviar_peticion.py` mientras Orquestación no exista) emite `SolicitarCotizacion.v1` → Cotizaciones resuelve → publica el resultado. Confirmar visualmente con `scripts/consumir_resultados.py` que llega al menos un resultado. Muestrear con `scripts/muestrear_metricas.py --duracion 120 --salida evidencias/e8/<corrida>/metricas-base.csv` para registrar el estado normal (backlog ≈ 0, consumidores = 1 por instancia activa).

## Caída (5 minutos)

- **En local:** `docker compose stop dev` (o el proceso Uvicorn de Cotizaciones), dejando `postgres` y `pulsar` arriba.
- **En Cloud Run:** `gcloud run services update <servicio> --scaling=0` (documentado en `docs/despliegue/cloud-run.md`, no ejecutado desde este repositorio).
- Antes de contar los 5 minutos, verificar con la API de administración que `subscriptions["cotizaciones-peticiones-v1"].consumers` está vacío.
- Durante la caída, seguir enviando tráfico a Entrada con normalidad (Entrada sigue confirmando y persistiendo, aunque el comando a Cotizaciones se acumule en el tópico).
- Muestrear con `scripts/muestrear_metricas.py --duracion 300 --salida evidencias/e8/<corrida>/metricas-caida.csv`: como Cotizaciones está caído, las filas de base de datos quedan congeladas y lo relevante es `topico_backlog` creciendo y `topico_consumidores = 0`.
- Registrar aparte la latencia de la orden de parada (desde que se emite el comando de apagado hasta que el broker confirma cero consumidores), separada de la ventana de 5 minutos de caída medida.

## Restauración

1. Restaurar Cotizaciones con la **misma imagen y configuración** (`docker compose up -d dev` o `--scaling=1` en Cloud Run). No tocar `COTIZACIONES_DATABASE_URL`, la suscripción ni el catálogo activo.
2. Medir desde la orden de restauración hasta que el backlog de `cotizaciones-peticiones-v1` vuelve a 0 mientras el tráfico de Entrada sigue activo (`scripts/muestrear_metricas.py` en la misma ventana, o `laboratorio.backlog_servicio()`/`GET .../stats` a mano).
3. No borrar el inbox ni el outbox ni reiniciar el cursor de la suscripción bajo ninguna circunstancia: el criterio de éxito depende de que la reentrega ocurra con el mismo cursor.

## Reconciliación

Cortar la cohorte de IDs de `id_peticion` generados durante la ventana de caída (y, si se quiere, también los de la línea base) usando el JSONL que produce `scripts/enviar_peticion.py --salida` (o el harness del equipo con el mismo formato: al menos `id_peticion` e `instante` por línea). Ejecutar:

```bash
python scripts/reconciliar.py --entrada evidencias/e8/<corrida>/enviados.jsonl \
  --desde <inicio_caida_iso> --hasta <fin_ventana_iso> \
  --salida evidencias/e8/<corrida>/reconciliacion.json
```

El script produce `elegibles`, `propuestas`, `rechazos`, `pendientes` (con sus IDs), `cotizaciones_duplicadas_por_peticion` (debe ser `[]`) y `salidas_por_cotizacion_invalidas` (debe ser `[]`); el campo `consistente` resume el criterio de éxito. Termina con código de salida distinto de 0 si la cohorte no cerró.

## Artefactos por corrida

```text
evidencias/e8/<corrida>/
  manifiesto.json        # fecha, commit, imagen, version de schemas, dimensionamiento
  enviados.jsonl         # cohorte de scripts/enviar_peticion.py --salida
  metricas-base.csv
  metricas-caida.csv
  metricas-recuperacion.csv
  reconciliacion.json
  logs/                  # docker logs / logs de Cloud Run de la ventana
```

## Criterio de éxito de Cotizaciones

**Cero pendientes de la cohorte al plazo y cero cotizaciones duplicadas** (`pendientes == []` y `cotizaciones_duplicadas_por_peticion == []` en `reconciliacion.json`). El criterio `A − D = ∅` (confirmadas por Entrada vs. registros durables) se mide del lado de Entrada, no aquí.

## Prohibiciones

- No borrar `mensajeria.inbox`, `mensajeria.outbox` ni sus filas para "destrabar" una corrida.
- No reiniciar el cursor de `cotizaciones-peticiones-v1` ni crear una suscripción nueva para reemplazarla.
- No confundir un mensaje en DLQ o pausado (`MensajeVenenoso`) con negocio completado: si el consumo queda `PAUSADO` (ver `/health/ready`), la corrida no es válida hasta corregir la causa y reiniciar el servicio completo.

## Límites

Esta ventana de 5 minutos no demuestra 99,9 % mensual, pérdida del broker o del host, recuperación regional, ni el cierre del Trabajo durante la caída. Verificado en esta fase solo con Cotizaciones aislada, sin los otros tres servicios reales (ver `docs/evidencias/07-recuperacion-y-escala.md` para los resultados obtenidos con el doble de Orquestación).
