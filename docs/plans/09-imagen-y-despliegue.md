# Fase 09 — Imagen, despliegue y sustentación (Pasos 60–65)

Corresponde a `planes-otros-microservicios/cotizaciones/08-despliegue-sustentacion.md`. Plataforma confirmada: un Cloud Run Service, Cloud SQL propio y Pulsar externo en VM. **Esta fase deja todo listo y documentado, pero no ejecuta `gcloud` ni crea recursos en la nube.**

---

## Paso 60 — Dockerfile

**Archivos:** `Dockerfile`, `.dockerignore`.

- Construcción en dos etapas sobre `python:3.12.3-slim`. uv 0.10.9 se copia desde su imagen oficial (verificar que exista la etiqueta).
- Primero se instalan las dependencias desde `pyproject.toml` y `uv.lock` sin el proyecto (capa cacheable); después se copian `src`, `alembic.ini`, `migraciones`, `scripts` y `datos`, y se instala el proyecto sin dependencias de desarrollo y sin modo editable.
- La etapa final lleva el entorno virtual y esos directorios, se ejecuta con un usuario no root y sin buffer de salida.
- Arranque: un solo proceso Uvicorn con la factoría `cotizaciones.api.app:create_app`, host `0.0.0.0`, puerto `PORT` (8002 por defecto), sin recarga y con cierre ordenado menor a 8 s. El proceso debe recibir SIGTERM directamente (arranque en forma exec; si se necesita expandir `PORT`, usar `exec` desde un shell).
- `.dockerignore` excluye `.venv`, cachés, `tests`, `docs` y `.git`.
- En este equipo con Apple Silicon, construir para `linux/amd64`, que es la plataforma de Cloud Run.

## Paso 61 — Laboratorio de la imagen

**Archivo:** `docker-compose.imagen.yaml`.

Motivo: el Pulsar de Entrada anuncia `127.0.0.1` y no es alcanzable desde un contenedor. Este Compose aislado tiene su propia red y contiene:
- PostgreSQL con un volumen distinto;
- Pulsar 4.1.3 standalone anunciando su nombre de servicio en la red interna;
- un servicio de preparación, con la misma imagen, que migra, carga y activa el catálogo v1 y prepara Pulsar;
- el servicio `cotizaciones`;
- un servicio `smoke` que ejecuta el Paso 62.

**Verificación:**
1. `docker compose -f docker-compose.imagen.yaml up` completa la preparación y el smoke.
2. `docker stop` del servicio con plazo de 10 s muestra en los logs un cierre ordenado menor a 10 s.
3. Al reiniciarlo, procesa lo pendiente con la misma base y la misma suscripción.

## Paso 62 — Smoke de despliegue

**Archivo:** `scripts/smoke_despliegue.py`.

Con `--api-url` y la URL de Pulsar:
1. Comprueba `/health/live` y `/health/ready`.
2. Envía F1 y F5 con el doble.
3. Consulta `GET /cotizaciones?id_peticion=…` hasta 30 s y verifica propuesta y rechazo.
4. Termina con código distinto de cero ante cualquier fallo.

Antes de enviar HTTP, espera que el servicio haya procesado un comando previo, para demostrar que consume sin tráfico HTTP.

## Paso 63 — Runbook de Cloud Run

**Archivo:** `docs/despliegue/cloud-run.md` (documento, no se ejecuta).

**Contenido:**
- **Prerrequisitos del equipo:** proyecto y región de laboratorio; repositorio de Artifact Registry; instancia Cloud SQL PostgreSQL 17 dedicada `cotizaciones-db`, con su base y usuario (registrar el costo de cuatro instancias); secreto en Secret Manager con `COTIZACIONES_DATABASE_URL`; salida VPC hacia la IP privada de Cloud SQL y de la VM de Pulsar; clúster Pulsar anunciando una dirección privada alcanzable (responsabilidad del encargado de infraestructura).
- **Parámetros del Service `cotizaciones`:** facturación por instancia (CPU disponible fuera de peticiones); escala manual 1 (0, 2 o 4 solo en experimentos, sin mezclar con autoescalamiento); una revisión activa; CPU y memoria fijas y registradas; variables de 00 §11; secreto montado como variable.
- **Tareas previas con la misma imagen:** Cloud Run Jobs para `alembic upgrade head`, carga del catálogo y `preparar_pulsar.py`. Nunca migrar al arrancar cada réplica.
- **Verificación posterior:** logs de arranque, `/health/ready`, consumidor conectado en las estadísticas de Pulsar, smoke del Paso 62 y un intervalo sin HTTP con avance durable.
- Cada flag se verifica contra la documentación oficial vigente (enlaces de `03-integracion-experimentos-y-entrega.md §3`) antes de ejecutarlo.

## Paso 64 — README final y guion

**Archivo:** `README.md`.

**Contenido:** arquitectura (un módulo, capas, un proceso por instancia); topología de datos descentralizada (base propia, sin tablas ni credenciales compartidas); mapa de mensajes con su clasificación; arranque, parada y recuperación; limitaciones.

**Guion de demo:**
1. Comando recibido.
2. Resolución con el catálogo y fila persistida.
3. Resultado leído por dos suscripciones.
4. Oferta homologada del partner correcto y rechazo legítimo.
5. Caída con aceptación en Entrada, aumento del backlog y recuperación.
6. Diferencia entre mensaje duplicado y cotización duplicada.
7. Duración estimada en E3.

## Paso 65 — Cierre

**Archivo:** `docs/evidencias/09-imagen-y-despliegue.md`.

- Ejecutar la verificación estándar completa y el laboratorio de la imagen.
- Lista de pendientes explícitos: integración con Orquestación real; clúster Pulsar del equipo; ejecución del despliegue en la nube; corridas grupales E8, E4 y E3.
- Registrar la sección de actividades del responsable de Cotizaciones para el documento grupal (ítem de la rúbrica), sin atribuir resultados no ejecutados.
