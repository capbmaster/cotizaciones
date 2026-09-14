# Evidencia 07 — Recuperación (E8) y escalamiento (E4)

Estado: **Fase 07 terminada** (Pasos 47–52). Fecha: 2026-09-14 (Bogotá). Entorno: contenedor `dev`; PostgreSQL 17.6 y Pulsar 4.1.3 del Compose, reales (no mockeados) en todas las pruebas de esta fase.

Esta fase demuestra la **corrección** de recuperación y escalamiento con Cotizaciones aislada (sin Entrada ni Orquestación reales todavía). Las corridas E8/E4 completas con los cuatro servicios y sus mediciones de rendimiento son trabajo del equipo, con los procedimientos de esta fase ya listos para ejecutarlas.

## Alcance terminado

| Paso | Archivos | Contenido |
|---|---|---|
| 47 | `scripts/{muestrear_metricas,reconciliar}.py`, `tests/integracion/test_scripts_experimento.py` | Ver detalle abajo. |
| 48 | `tests/integracion/test_recuperacion.py` | Caída y recuperación con dos cohortes reales sobre Pulsar y PostgreSQL. |
| 49 | `tests/integracion/test_concurrencia.py` (ampliación) | 2 y 4 instancias FastAPI completas bajo 200 comandos con reentregas mixtas. |
| 50 | `docs/experimentos/e8-cotizaciones.md` | Procedimiento de laboratorio para la corrida grupal E8. |
| 51 | `docs/experimentos/e4-cotizaciones.md` | Procedimiento de laboratorio para la corrida grupal E4. |
| 52 | Esta evidencia, README (sección "Recuperación y escalamiento") | Cierre de fase. |

### Paso 47 — Scripts de métricas y reconciliación

- **`muestrear_metricas.py`** (solo lectura): cada `--intervalo` segundos durante `--duracion`, añade una fila a un CSV con: totales de cotizaciones/propuestas/rechazos; nuevas en el intervalo (`registrada_en` desde el último corte); percentiles p50/p95/p99 de latencia comando→efecto (`registrada_en - instante_comando`, calculados a mano sin dependencias nuevas); pendientes del outbox y su antigüedad (`RepositorioOutbox.metricas()`); backlog, tasa de salida y consumidores conectados de `cotizaciones-peticiones-v1` vía la API de administración de Pulsar. Cada fila también se imprime como JSON en stdout.
- **`reconciliar.py`**: lee el JSONL de peticiones esperadas (el que produce `scripts/enviar_peticion.py --salida`), descarta las líneas cuyo `modo` es una reentrega de la misma petición (`repetido`, `nuevo-comando`, `contradictoria`) para no contarlas como elegibles adicionales, y opcionalmente acota por ventana (`--desde`/`--hasta`). Produce `reconciliacion.json` con `elegibles`, `propuestas`, `rechazos`, `pendientes` (con IDs), `cotizaciones_duplicadas_por_peticion` (debe ser `[]`) y `salidas_por_cotizacion_invalidas` (cotizaciones sin exactamente una salida enviada; debe ser `[]`). Separa dos conceptos:
  - `cuadre_contable`: la identidad `elegibles = propuestas + rechazos + pendientes` (verificación de conteo, siempre debería cumplirse);
  - `consistente`: el criterio de éxito real (cero pendientes, cero duplicados, cero salidas inválidas). El proceso termina con código 1 si `consistente` es falso.

**Prueba roja:** antes de escribir los scripts, `tests/integracion/test_scripts_experimento.py` fallaba con `FileNotFoundError`/`ModuleNotFoundError` al invocar `scripts/muestrear_metricas.py` y `scripts/reconciliar.py`, que no existían.

**Pruebas (3, con una base sembrada de verdad):**
- `test_muestrear_metricas_produce_una_fila_con_los_conteos_sembrados`: siembra F1 (propuesta) y F5 (rechazo), corre el script y verifica `total_cotizaciones=2`, `total_propuestas=1`, `total_rechazos=1`, `outbox_pendientes=2`.
- `test_reconciliar_produce_los_conteos_esperados`: siembra propuesta y rechazo, despacha sus salidas con un publicador falso, deja una tercera petición sin procesar; verifica `elegibles=3`, `pendientes=[esa_id]`, `cuadre_contable=True`, `consistente=False`; al resolver el pendiente y despacharlo, `consistente=True`.
- `test_reconciliar_ignora_reentregas_de_la_misma_peticion`: un JSONL con `modo=original` y `modo=repetido` de la misma `id_peticion` cuenta como **una sola** elegible.

### Paso 48 — Caída y recuperación

`tests/integracion/test_recuperacion.py::test_caida_y_recuperacion_con_dos_cohortes`, sobre Pulsar y PostgreSQL reales (fixture `laboratorio`, tópicos únicos por prueba):

1. Servicio arriba (`with TestClient(create_app(...))`), se envía la cohorte A (5 peticiones) y se espera que las 5 se resuelvan y publiquen; backlog vuelve a 0.
2. **El `with` se cierra** (cae API, consumo y despacho juntos). Se envía la cohorte B (5 peticiones) con el servicio detenido: se espera que el backlog crezca a 5 y se confirma que ninguna fila nueva aparece en la base.
3. Se reabre `create_app` con la **misma** `laboratorio.configuracion` (misma base, misma suscripción `cotizaciones-peticiones-v1`, mismos tópicos): la cohorte B se resuelve sin tocar A; backlog vuelve a 0.
4. Se reconcilia A ∪ B invocando `scripts/reconciliar.py` como subproceso real: `pendientes=[]`, `cotizaciones_duplicadas_por_peticion=[]`, `salidas_por_cotizacion_invalidas=[]`, y `marcas_sin_efecto(base) == 0` (ninguna marca de inbox sin su cotización correspondiente).

**Prueba roja:** el primer intento de la prueba importaba `scripts.reconciliar` como módulo Python (`ModuleNotFoundError: No module named 'scripts'`, porque `scripts/` no está en el `sys.path` con `--import-mode=importlib`); se corrigió invocando el script como subproceso, igual que el resto de las pruebas de integración que usan scripts.

### Paso 49 — Réplicas concurrentes completas bajo carga

`tests/integracion/test_concurrencia.py::test_replicas_concurrentes_completas_bajo_carga_no_duplican`, parametrizada en `[2, 4]` instancias:

- Cohorte de 200 mensajes: 170 peticiones originales distintas, 20 reentregas exactas (mismo `command_id`, mismo contenido — ~10 %) y 10 reenvíos de una petición existente con otro `command_id` (mismos datos de negocio, incluido `id_trabajo` — ~5 %), barajados con semilla fija.
- Se envían los 200 mensajes al tópico de la prueba y luego se levantan 2 (o 4) apps FastAPI completas (`create_app`, cada una con su propia `Database` vía `laboratorio.configuracion`) sobre la misma suscripción.
- Se espera que las 170 cotizaciones únicas existan y que las 170 salidas se confirmen.
- Verificación con SQL directo: cero `id_peticion` con más de una fila en `cotizaciones.cotizaciones`; cada `id_evento` en `mensajeria.outbox` tiene exactamente una fila y esa fila está `enviada_en IS NOT NULL` (ninguna reserva confirmada dos veces, ninguna salida duplicada); `marcas_sin_efecto(base) == 0`.
- Se instrumentó `RepositorioOutbox.confirmar` (solo en la prueba, vía `patch.object`) para capturar el `propietario` de cada reserva **antes** de que la confirmación lo limpie a `NULL`, y así registrar cuántas salidas confirmó cada instancia.

**Prueba roja/bug real encontrado:** la primera versión generaba el reenvío "misma petición, otro comando" con un `id_trabajo` aleatorio nuevo (reutilizando el generador `peticion_nueva()` completo). Como `id_trabajo` es parte de los datos de negocio de `DatosPeticion`, el dominio lo trató correctamente como una **petición contradictoria** (`ConflictoPeticion`), que el consumidor convierte en `MensajeVenenoso` y **pausa el ciclo de consumo** — el test se colgó 90 s hasta el timeout de `esperar()`. El log de la corrida fallida lo muestra explícitamente: `Ciclo consumo-peticiones pausado por el mensaje …: ConflictoPeticion: La peticion ya fue resuelta con otros datos`. Se corrigió generando el reenvío como una copia exacta del mensaje original con solo el `command_id` cambiado, que es el caso real de "mismo comando de negocio, mensaje reenviado".

**Resultados reales de la corrida** (semilla fija, reproducible):

| Instancias | Peticiones únicas | Distribución de salidas confirmadas por propietario | Duración |
|---|---:|---|---:|
| 2 | 170 | `{80, 90}` | 2,18 s |
| 4 | 170 | `{46, 42, 68, 14}` | 2,67 s |

La distribución desigual entre propietarios es esperable (Shared no garantiza reparto uniforme por lote corto); lo que importa para la corrección es que la suma coincide exactamente con las 170 peticiones únicas y que ninguna se duplicó.

### Paso 50–51 — Procedimientos de laboratorio

`docs/experimentos/e8-cotizaciones.md` y `docs/experimentos/e4-cotizaciones.md`: documentos de procedimiento, no código. Cubren preparación (dimensionamiento de backlog/retención acorde a `scripts/preparar_pulsar.py`), línea base, ventana de caída/carga, restauración, reconciliación con `scripts/reconciliar.py`, artefactos por corrida (`evidencias/e8|e4/<corrida>/`) y prohibiciones (nunca borrar inbox/outbox, nunca reiniciar cursores ni crear suscripciones nuevas). Registran también los límites heredados (no se demuestra 99,9 % mensual, ni 48 h continuas, ni autoescalamiento) y la brecha B2C, que no aplica a Cotizaciones.

## Pruebas nuevas y suite completa

| Archivo | Pruebas |
|---|---|
| `tests/integracion/test_scripts_experimento.py` | 3 |
| `tests/integracion/test_recuperacion.py` | 1 |
| `tests/integracion/test_concurrencia.py` (nuevas; 3 ya existían) | 2 (parametrizada `[2, 4]`) |

Nuevas: 6. Suite completa: **444 passed** en ~36 s (incluye las 15 pruebas de Pulsar/ciclo de vida de la Fase 05 y la de consultas HTTP de la Fase 06, todas contra infraestructura real).

## Comandos ejecutados y resultado

| Comando | Resultado |
|---|---|
| `uv run --locked pytest tests -q -s --tb=short` | **444 passed**, 1 warning (Starlette/anyio, de terceros) |
| `uv run --locked ruff check .` / `ruff format --check .` | All checks passed / 150 files already formatted |
| `uv run --locked mypy src tests scripts migraciones` | Success: no issues found in 127 source files |
| `uv run --locked python scripts/verify_distribution.py` | Wheel instalado importado fuera del árbol fuente, sin cambios de contrato en esta fase (los scripts nuevos son standalone, no parte del paquete importable) |
| `git diff --check` | Sin salida, exit 0 |

## Decisiones y desviaciones

- **`consistente` ≠ `cuadre_contable` en `reconciliar.py`:** el plan pide comprobar la identidad `elegibles = propuestas + rechazos + pendientes`, pero esa identidad es una verificación de conteo (siempre se cumple si el script no tiene un bug), no un criterio de éxito. Se separaron los dos conceptos explícitamente para que el código de salida del script (0/1) refleje el criterio real de E8: cero pendientes, cero duplicados, cero salidas inválidas.
- **`reconciliar.py` se invoca por subproceso, no se importa como módulo**, porque `scripts/` no es un paquete instalado (no tiene `__init__.py` ni está en `sys.path` bajo `--import-mode=importlib`). Es el mismo patrón que ya usaban `test_catalogo.py` y `test_scripts_experimento.py` con `cargar_catalogo.py`.
- **Percentiles calculados a mano** (sin `numpy` ni `statistics.quantiles`) para no añadir una dependencia nueva solo para un script de laboratorio.
- **El reparto de trabajo por propietario solo es observable con una instrumentación de prueba** (`patch.object` sobre `RepositorioOutbox.confirmar`), porque el campo `propietario` de la reserva se limpia a `NULL` en el mismo `UPDATE` que la confirma (diseño correcto del outbox: no hay razón productiva para conservarlo). Esa instrumentación vive solo en el test, no se tocó el código de producción.

## Limitaciones

- **No se ejecutaron corridas E8/E4 reales de varios minutos** (2 min de línea base, 5 min de caída, 10 min por condición de carga): los procedimientos de los Pasos 50–51 quedan listos, pero la corrida completa requiere el equipo, Entrada y (para E4) potencialmente Orquestación real, y se anexa después.
- **La calibración de λ no se ejecutó**: no hay todavía un generador de carga sostenida del equipo ni Orquestación real para medir la capacidad sostenida de un extremo a otro; `docs/experimentos/e4-cotizaciones.md` deja el procedimiento y permite `COTIZACIONES_RETARDO_LABORATORIO_MS` como salida sintética documentada si hiciera falta.
- **La brecha B2C sigue sin resolver**, como en las fases anteriores: no es una operación de Cotizaciones.
- Pendientes heredados sin resolver: `connect_timeout` de PostgreSQL (evidencia 01) e integración real con Orquestación (se sigue usando el doble `enviar_peticion.py`).

## Siguiente dependencia

Fase 08 (Pasos 53–59): evolución E3 de `CotizacionRegistrada` con `duracion_estimada_minutos` opcional (revisión 2, compatible), con Seguimiento como líder del experimento. Empieza con el Paso 53 (punto de control: congelar v1, pedir autorización de commit y tag `cotizaciones-v1.0.0`).
