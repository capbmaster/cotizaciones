# Fase 07 — Recuperación (E8) y escalamiento (E4) (Pasos 47–52)

Corresponde a `planes-otros-microservicios/cotizaciones/07-recuperacion-escalabilidad.md` y a las secciones 6 y 8 de `03-integracion-experimentos-y-entrega.md`. En E8, Cotizaciones es **el servicio que falla**; el artefacto evaluado es Entrada. En E4, Cotizaciones es el servicio que se escala (1/2/4 instancias completas). No se añade latencia artificial al dominio.

---

## Paso 47 — Métricas y reconciliación

**Archivos:** `scripts/muestrear_metricas.py`, `scripts/reconciliar.py`, `tests/integracion/test_scripts_experimento.py`.

- `muestrear_metricas.py` (solo lectura): cada `--intervalo` segundos (por defecto 5) durante `--duracion`, añade una fila a un CSV con: instante UTC; totales de cotizaciones, propuestas y rechazos; nuevas en el intervalo; latencia comando → efecto (`registrada_en` − `instante_comando`: p50, p95 y p99 del intervalo, marcada como distribuida con posible desfase de reloj); pendientes del outbox y antigüedad del más viejo; backlog, tasa de salida y consumidores conectados de `cotizaciones-peticiones-v1`, según las estadísticas de administración de Pulsar.
- `reconciliar.py`: recibe el JSONL de peticiones esperadas (del doble o del harness del equipo) y, opcionalmente, una ventana de cohorte. Produce `reconciliacion.json` con elegibles, propuestas, rechazos, pendientes (con IDs), cotizaciones duplicadas por petición (debe ser 0) y salidas por cotización (exactamente 1, enviada). Comprueba `elegibles = propuestas + rechazos + pendientes`.

**Prueba:** con una base pequeña sembrada, ambos scripts producen los conteos esperados.

## Paso 48 — Prueba automatizada de caída y recuperación

**Archivo:** `tests/integracion/test_recuperacion.py`.

```text
iniciar el servicio (lifespan) y enviar la cohorte A → esperar que A se resuelva
cerrar el lifespan (caen juntos API, consumo y despacho)
enviar la cohorte B con el servicio detenido → comprobar backlog > 0 y ninguna fila de B
reabrir con la misma base, suscripción y configuración → esperar con plazo que B se resuelva
reconciliar A ∪ B: cero pendientes, cero duplicados, una salida enviada por cotización, inbox intacto
```

## Paso 49 — Prueba de réplicas concurrentes

**Archivo:** `tests/integracion/test_concurrencia.py` (ampliación).

Con 2 y luego 4 apps (cada una con su propia `Database`) sobre la misma suscripción, enviar 200 comandos: un 10 % repite `command_id` y un 5 % repite la petición con otro comando. Afirmar: una cotización por petición, una salida confirmada por cotización y ninguna reserva confirmada dos veces. Registrar cuántos procesó cada propietario. Esta prueba verifica corrección, no rendimiento.

## Paso 50 — Procedimiento E8 de Cotizaciones

**Archivo:** `docs/experimentos/e8-cotizaciones.md`.

**Contenido obligatorio:**
- Preparación: catálogo activo, suscripciones y retención preparadas antes del tráfico, dimensionadas para 5 min de caída (backlog ≈ tasa × duración).
- Línea base de 2 min con el recorrido completo.
- Caída de 5 min: en local, detener todos los procesos o contenedores de Cotizaciones; en Cloud Run, escala manual 0. Antes de contar el tiempo, verificar en las estadísticas del tópico que hay cero consumidores. El resto del sistema sigue activo.
- Durante la caída: muestrear métricas y registrar el backlog.
- Restauración con la misma imagen y configuración (escala 1 en Cloud Run); medir desde la orden de restauración hasta drenar la cohorte mientras continúa el tráfico.
- Reconciliación con `reconciliar.py` sobre la cohorte cortada.
- Artefactos en `evidencias/e8/<corrida>/`: manifiesto, `metricas.csv`, `reconciliacion.json` y logs.
- Prohibido borrar el inbox, reiniciar cursores o crear una suscripción nueva.

Criterio de Cotizaciones: cero pendientes de la cohorte al plazo y cero cotizaciones duplicadas. El criterio A − D = ∅ se mide en Entrada.

## Paso 51 — Procedimiento E4 de Cotizaciones

**Archivo:** `docs/experimentos/e4-cotizaciones.md`.

**Contenido obligatorio:**
- Calibrar λ con 1 instancia y congelarlo.
- Condiciones: A (λ, 1 instancia), B (4λ, 1), C (4λ, 2) y D (4λ, 4). Cada una con 2 min de calentamiento y 10 min medidos, tres repeticiones y orden alternado.
- En local, N procesos Uvicorn con la misma configuración en los puertos 8002, 8012, 8022 y 8032. En Cloud Run, escala manual.
- Recursos idénticos por réplica. Registrar que las conexiones SQL totales, N × (pool + overflow), caben en `max_connections`.
- Métricas del Paso 47: throughput de nuevas cotizaciones, nunca tasa de ACK.
- `COTIZACIONES_RETARDO_LABORATORIO_MS` solo si la calibración no genera presión; en ese caso, rotular los resultados como sintéticos.
- No afirmar autoescalamiento ni operación de 48 h.

## Paso 52 — Evidencia 07

**Archivos:** `docs/evidencias/07-recuperacion-y-escala.md`, README (sección de recuperación).

Registrar resultados de los Pasos 48–49, los procedimientos listos para la corrida grupal y sus límites. Las corridas completas E8/E4 con los cuatro servicios se ejecutan con el equipo y se anexan después.
