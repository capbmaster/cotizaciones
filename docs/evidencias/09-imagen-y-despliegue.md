# Fase 09 — Imagen, despliegue y sustentación (Pasos 60–65)

Fecha: 2026-09-14 (Bogotá). Commit base: `a9b9158` (Fase 08 ya committeada). Los Pasos 60–62
(Dockerfile, laboratorio de imagen, smoke de despliegue) se adelantaron durante el Paso 53 —ver
[docs/contratos/CONGELACION-v1.md](../contratos/CONGELACION-v1.md)— y se re-verificaron aquí sobre
el código de la Fase 08 (escritor v2 de E3 incluido). Esta fase **no ejecuta `gcloud`** ni crea
recursos en la nube; el runbook (Paso 63) es un documento.

## Resumen por paso

| Paso | Entregable | Estado |
|---|---|---|
| 60 | `Dockerfile`, `.dockerignore` | Cerrado (Paso 53), re-verificado aquí |
| 61 | `docker-compose.imagen.yaml` | Cerrado (Paso 53), re-verificado aquí |
| 62 | `scripts/smoke_despliegue.py` | Cerrado (Paso 53), re-verificado aquí |
| 63 | `docs/despliegue/cloud-run.md` | Cerrado (documento, no ejecutado) |
| 64 | `README.md` (arquitectura, topología, guion de demo, limitaciones) | Cerrado |
| 65 | Este documento | Cerrado |

## Verificación estándar (dentro de `dev`)

```
pytest tests -q                        → 488 passed
ruff check .                           → All checks passed!
ruff format --check .                  → 158 files already formatted
mypy src tests scripts migraciones     → Success: no issues found in 134 source files
python scripts/verify_distribution.py  → wheel instalado e importado fuera del árbol fuente, sin error
```

En el host: `git diff --check` sin advertencias.

## Laboratorio de la imagen (re-ejecutado sobre el código de la Fase 08)

Construida `docker build --platform linux/amd64 -t cotizaciones:v1 .` con el commit `a9b9158`
(incluye el escritor v2 de E3). Imagen resultante:
`sha256:b5b4f3376496510efd85c7d7622570d1270b3cd77b9245ce8c313e3fc0b7f0ef` (local, no publicada a
un registro; distinta de la imagen v1 congelada del Paso 53,
`sha256:41910a3185e7cc7c642c549c5ad4c1b569d3fb8f1c76754491473c8b5404acd8`, porque incluye el
código de E3).

Ejecutado con `docker-compose.imagen.yaml up -d` (sin `--abort-on-container-exit`: ese flag detiene
todo el stack en cuanto el servicio de un solo uso `preparacion` termina con éxito, una condición
de carrera que no existía cuando el Paso 53 usó el flag por primera vez con tiempos distintos; se
documenta aquí para que quien reproduzca el laboratorio no la repita):

| Verificación | Resultado |
|---|---|
| `preparacion` (migra `0002_duracion_estimada`, carga/activa catálogo v1, prepara Pulsar) | Exit code 0 |
| `cotizaciones` arranca sano | `/health/ready` 200, ambos componentes `OPERANDO` |
| `smoke` (`scripts/smoke_despliegue.py`) | `SMOKE OK`, exit 0: F1 → PROPUESTA `a101`; F5 → RECHAZADA `SIN_OFERTA_PARA_CATEGORIA` |
| `docker compose stop -t 10 cotizaciones` | Cierre ordenado en **~1.2 s** (`Shutting down` → `Application shutdown complete` → `Finished server process`) |
| Reinicio (`docker compose start cotizaciones`) | `/health/ready` 200 de inmediato; las 2 cotizaciones sembradas por el smoke siguen en la base (`SELECT count(*)` antes y después = 2) |

Es el mismo comportamiento observado en el Paso 53 con la imagen v1 pura: la Fase 08 no cambió el
Dockerfile, `docker-compose.imagen.yaml` ni el ciclo de vida — solo el contenido que la aplicación
escribe.

## Pendientes explícitos

Lo siguiente **no** se ha ejecutado ni demostrado en el alcance de este servicio, y no debe
atribuirse como resultado logrado en el documento grupal:

- **Integración con Orquestación real:** Orquestación no existe todavía como código en el curso;
  todo comando recibido en las pruebas y en el laboratorio de imagen proviene del doble
  (`enviar_peticion.py` / el productor embebido de `smoke_despliegue.py`), nunca del servicio real.
- **Integración con Seguimiento real:** igual que arriba; las suscripciones
  `seguimiento-cotizacion-registrada` y `seguimiento-cotizacion-rechazada-v1` existen para que
  Seguimiento las consuma cuando exista, pero hoy no las consume nadie real.
- **Clúster Pulsar del equipo:** no se ha provisionado; todas las pruebas usan un Pulsar standalone
  local (Compose) o efímero (CI), nunca el clúster compartido en VM que describe
  `docs/despliegue/cloud-run.md`.
- **Ejecución del despliegue en la nube:** ningún comando `gcloud` de `docs/despliegue/cloud-run.md`
  se ha corrido; no existen proyecto, instancia Cloud SQL, secreto ni Service de Cotizaciones en
  Cloud Run.
- **Corridas grupales E8, E4 y E3:** los tres experimentos están verificados con pruebas
  automatizadas y con el laboratorio de imagen local (recuperación, réplicas concurrentes,
  compatibilidad de esquema y F8), pero ninguno se ha ejecutado como la corrida formal y
  cronometrada que describen `docs/experimentos/e8-cotizaciones.md`,
  `docs/experimentos/e4-cotizaciones.md` y `docs/experimentos/e3-cotizaciones.md` (calibración de
  λ, condiciones con calentamiento y repeticiones, coordinación multi-servicio de los seis brazos
  de E3). Esa ejecución requiere los cuatro microservicios desplegados a la vez, lo que a su vez
  depende de los tres puntos anteriores.

## Actividades del responsable de Cotizaciones (para el documento grupal)

Implementación completa de las Fases 01 a 09 del microservicio Cotizaciones: dominio y aplicación
(catálogo versionado, resolución de ofertas, agregado `Cotizacion`), persistencia con patrón
outbox/inbox para efecto exactamente una vez, integración con Apache Pulsar (consumo, despacho,
esquemas Avro), consultas HTTP de solo lectura, recuperación ante caída y escalamiento horizontal
verificado con réplicas reales, evolución de esquema aditiva para el experimento E3
(`duracion_estimada_minutos`) con compatibilidad de broker verificada contra un Pulsar real, y
empaquetado en una imagen Docker con laboratorio de verificación end-to-end y runbook de
despliegue en Cloud Run. Todo el trabajo quedó respaldado por pruebas automatizadas (488 al cierre
de esta fase), verificación estática (ruff, mypy estricto) y evidencia escrita por fase en
`docs/evidencias/`. No se atribuye ningún resultado de integración real con Orquestación,
Seguimiento, el clúster Pulsar del equipo ni el entorno de Cloud Run, por las razones listadas en
«Pendientes explícitos».
