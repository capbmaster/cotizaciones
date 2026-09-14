# E4 — Escalamiento de Cotizaciones ante 4× demanda

Cotizaciones es el servicio que se escala: 1, 2 y 4 instancias completas (API + consumo + despacho en cada una, tal como arranca `create_app`). No se demuestra autoescalamiento ni operación de 48 h; el recorte es 2 min de calentamiento y 10 min medidos por condición, tres repeticiones, orden alternado.

## Calibración de λ

Con **1 instancia**, generar tráfico creciente con `scripts/enviar_peticion.py --cantidad N` (o el harness del equipo) hasta observar presión sostenida (backlog de `cotizaciones-peticiones-v1` que no vuelve a 0 entre lotes, medido con `scripts/muestrear_metricas.py`). Fijar λ como una tasa por debajo de ese punto (referencia: ~50 % de la capacidad sostenida observada) y **congelarla** antes de comparar condiciones. Registrar cómo se obtuvo λ en el manifiesto de la corrida; no se recalibra entre condiciones.

Si con `pulsar-client` y PostgreSQL locales 4λ no genera presión perceptible (la POC es liviana), se permite `COTIZACIONES_RETARDO_LABORATORIO_MS` > 0 para forzar contención, pero entonces **todos** los resultados de esa corrida se rotulan explícitamente como sintéticos en el informe, y se reporta el valor usado.

## Condiciones

| Condición | Llegada ofrecida | Instancias completas |
|---|---:|---:|
| A | λ | 1 |
| B | 4λ | 1 |
| C | 4λ | 2 |
| D | 4λ | 4 |

Cada condición: 2 min de calentamiento (no medido) + 10 min medidos, × 3 repeticiones, con el orden de condiciones alternado entre repeticiones para limitar sesgo de caché/calor. Usar el mismo dataset/semilla de peticiones (categorías del catálogo de 00 §9) en las cuatro condiciones.

## Cómo escalar Cotizaciones

- **Local:** N procesos Uvicorn independientes con la **misma imagen/config**, en los puertos 8002, 8012, 8022 y 8032, todos apuntando a la misma `COTIZACIONES_DATABASE_URL` y la misma suscripción `cotizaciones-peticiones-v1`. Verificado en `tests/integracion/test_concurrencia.py::test_replicas_concurrentes_completas_bajo_carga_no_duplican` que 2 y 4 instancias reales (cada una con su propio proceso FastAPI, su propio `Database` y su propio despachador) no duplican cotizaciones ni salidas bajo una cohorte con reentregas mixtas.
- **Cloud Run:** escala manual al número de instancias de la condición (nunca autoescalamiento durante la medición); esperar a que el número de instancias observado se estabilice antes de empezar el calentamiento.
- Recursos idénticos por réplica en todas las condiciones (mismo `COTIZACIONES_DB_POOL_SIZE`/`COTIZACIONES_DB_MAX_OVERFLOW`, misma CPU/memoria en Cloud Run).

## Conexiones SQL

Con N instancias, el total de conexiones que Cotizaciones puede abrir es `N × (COTIZACIONES_DB_POOL_SIZE + COTIZACIONES_DB_MAX_OVERFLOW)`. Con los valores por defecto (5 + 5) y D = 4 instancias, son 40 conexiones. Verificar antes de la corrida D que `40 ≤ max_connections` de la instancia PostgreSQL usada (local o Cloud SQL), dejando margen para otros clientes (scripts de muestreo, `psql` manual). Registrar el valor efectivo de `max_connections` en el manifiesto.

## Métricas (del Paso 47)

Muestrear cada condición con:

```bash
python scripts/muestrear_metricas.py --intervalo 5 --duracion 600 \
  --admin-url <admin> --salida evidencias/e4/<corrida>/<condicion>.csv
```

Métricas relevantes del CSV: `nuevas_en_intervalo` (throughput real de **nuevas cotizaciones persistidas**, nunca la tasa de ACK ni de mensajes recibidos — una reentrega o un mensaje repetido no es throughput útil), `latencia_p50_s`/`p95_s`/`p99_s` (comando→efecto, distribuida y con posible desfase de reloj entre el generador y PostgreSQL), `outbox_pendientes` y su antigüedad, y `topico_backlog`/`topico_consumidores` de la suscripción propia. Registrar backlog en ventanas de 60 s para observar tendencia durante la fase estable (no solo el promedio de los 10 minutos, que puede ocultar picos).

Éxito técnico de cada condición: capacidad efectiva (`nuevas_en_intervalo` sostenido) al menos igual a la llegada elegible, sin crecimiento sostenido de `outbox_pendientes` ni de `topico_backlog`, y drenaje del backlog residual dentro de un plazo fijo (propuesta: 5 min) al cerrar la condición.

## Brecha B2C

Este microservicio no expone una operación B2C propia (no hay "consulta de marketplace" en Cotizaciones); el criterio B2C ≤10 % de degradación de E4 se mide, si el equipo lo implementa, sobre una operación de Orquestación (p. ej. consulta de estado de un Trabajo), no sobre Cotizaciones. Queda **no demostrado** en el alcance de este servicio, según lo previsto en `03-integracion-experimentos-y-entrega.md §8`.

## Límites

Escalar manualmente demuestra capacidad horizontal bajo carga corta (10 min por condición), no autoescalamiento por backlog ni operación sostenida de 48 h. El dimensionamiento de conexiones y de retención de Pulsar es una verificación previa, no evidencia experimental de producción continua.
