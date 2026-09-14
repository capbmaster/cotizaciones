# Runbook de Cloud Run — Cotizaciones

**Este documento no se ejecuta.** Describe cómo desplegar la imagen `cotizaciones` en Cloud Run
cuando el equipo tenga proyecto, Cloud SQL y el clúster de Pulsar del curso disponibles. Ningún
comando `gcloud` de este archivo se ha corrido; los recursos que nombra (proyecto, instancia,
secreto, servicio) no existen todavía.

Plataforma confirmada por el equipo (`03-integracion-experimentos-y-entrega.md §3`): un Cloud Run
Service, una instancia Cloud SQL propia para Cotizaciones y un clúster Pulsar externo en una VM
compartida por los cuatro microservicios.

## Prerrequisitos del equipo (no de este servicio)

Estos recursos los provisiona el equipo o la persona encargada de infraestructura; Cotizaciones
solo los consume:

- **Proyecto y región** de laboratorio, ya asignados por el curso.
- **Repositorio de Artifact Registry** (Docker) en la misma región, para `cotizaciones:vN`.
- **Instancia Cloud SQL PostgreSQL 17** dedicada, `cotizaciones-db`, con su propia base de datos y
  usuario (nunca compartidos con otro microservicio — topología descentralizada, ver README).
  Registrar el costo de horas-instancia si se levantan las cuatro bases del curso en paralelo.
- **Secreto en Secret Manager** con `COTIZACIONES_DATABASE_URL` completa
  (`postgresql+psycopg://usuario:contraseña@<ip-privada>:5432/cotizaciones`).
- **Salida VPC (VPC egress / conector Serverless VPC Access)** desde el Service hacia la IP
  privada de Cloud SQL y hacia la VM de Pulsar. Sin esto, el Service no alcanza ninguno de los
  dos.
- **Clúster Pulsar** anunciando una dirección **privada** alcanzable desde la VPC del Service
  (`advertised-address` del broker, no `127.0.0.1` ni `localhost`) — responsabilidad de quien
  administra la VM de Pulsar, no de este servicio.

Cada uno de estos puntos se verifica contra la documentación oficial de Cloud Run, Cloud SQL y
Serverless VPC Access vigente al momento del despliegue real (enlaces en
`03-integracion-experimentos-y-entrega.md §3`) antes de ejecutar cualquier `gcloud`; los nombres de
flags de este documento son de referencia y pueden cambiar de versión.

## Parámetros del Service `cotizaciones`

- **Facturación:** por instancia (`--no-cpu-throttling` o equivalente), no solo por petición —
  Cotizaciones mantiene dos hilos de fondo (consumo y despacho) que deben seguir corriendo entre
  peticiones HTTP.
- **Escala manual:** `--min-instances=1 --max-instances=1` en operación normal. Para los
  experimentos E4 (`docs/experimentos/e4-cotizaciones.md`), cambiar manualmente a 2 o 4 instancias
  **sin** activar autoescalamiento (`--max-instances` igual a `--min-instances` en cada condición);
  nunca mezclar escala manual y autoescalamiento en la misma corrida.
- **Una revisión activa** (`--no-traffic` en revisiones de prueba, tráfico 100 % a la revisión
  vigente): evita que dos versiones del escritor (por ejemplo v1 y v2 de E3) reciban tráfico a la
  vez de forma no controlada.
- **CPU y memoria fijas**, registradas en el manifiesto de cada despliegue (por ejemplo 1 vCPU /
  512 MiB como punto de partida; ajustar y anotar el valor real usado, no un valor supuesto).
- **Variables de entorno:** las de `docs/plans/00-contratos-y-datos.md §11`
  (`COTIZACIONES_PULSAR_URL`, `COTIZACIONES_TOPICO_*`, `COTIZACIONES_SUSCRIPCION_PETICIONES`,
  `COTIZACIONES_DB_POOL_SIZE`/`COTIZACIONES_DB_MAX_OVERFLOW`, etc.), todas con valores explícitos
  registrados junto al despliegue.
- **`COTIZACIONES_DATABASE_URL`** montada como variable de entorno **desde el secreto**
  (`--set-secrets`), nunca en texto plano en la configuración del Service.
- `PORT` la inyecta Cloud Run; el `Dockerfile` ya arranca Uvicorn en `0.0.0.0:${PORT}` (Paso 60).

## Tareas previas, con la misma imagen (Cloud Run Jobs)

Nunca migrar ni preparar Pulsar al arrancar una réplica del Service — cada arranque de réplica
debe encontrar el esquema y el catálogo ya listos. Con la **misma imagen** que el Service, tres
Cloud Run Jobs de un solo uso, ejecutados en orden antes de desplegar o de enrutar tráfico a una
revisión nueva:

1. `alembic upgrade head` — aplica las migraciones pendientes (incluida `0002_duracion_estimada`
   en E3) sobre `cotizaciones-db`.
2. Carga y activación del catálogo vigente: `python scripts/cargar_catalogo.py --archivo
   datos/catalogos/catalogo-vN.json --activar` (v1 en el despliegue inicial; v2 al activar E3, sin
   tocar la v1 — Paso 56).
3. `python scripts/preparar_pulsar.py --admin-url <admin-pulsar> [--compatibilidad
   FULL_TRANSITIVE]` — registra los esquemas Avro, crea las suscripciones durables de
   `docs/plans/00-contratos-y-datos.md §1` y, en E3, fija la compatibilidad del tópico de
   propuestas (Paso 57).

Cada Job usa las mismas variables de entorno y el mismo secreto que el Service, salvo que no
necesita `PORT`.

## Verificación posterior al despliegue

Sin ejecutar nada de esto todavía, la secuencia prevista es:

1. **Logs de arranque:** confirmar en Cloud Logging que el `lifespan` inició los hilos
   `consumo-peticiones` y `despacho-resultados` sin errores, y que no hay reintentos de conexión a
   Cloud SQL ni a Pulsar.
2. **`/health/ready`** responde 200 con ambos componentes `OPERANDO` (Cloud Run también lo usa como
   *readiness probe* si se configura explícitamente).
3. **Consumidor conectado** en las estadísticas de administración de Pulsar
   (`GET /admin/v2/persistent/public/default/solicitar-cotizacion-v1/stats`): la suscripción
   `cotizaciones-peticiones-v1` debe aparecer con un consumidor activo.
4. **Smoke del Paso 62:** `python scripts/smoke_despliegue.py --api-url <url-cloud-run>
   --pulsar-url <pulsar-privado>` desde una máquina con salida hacia ambos endpoints (o como Job
   puntual con la misma imagen).
5. **Intervalo sin tráfico HTTP con avance durable:** enviar una petición solo por Pulsar (doble de
   Orquestación) y confirmar en Cloud SQL, sin ninguna llamada HTTP a Cotizaciones, que la fila
   quedó persistida — demuestra que el consumo no depende de que alguien esté consultando la API.

## Fuera de alcance de este runbook

- No cubre el despliegue de la VM de Pulsar en sí (es compartida por los cuatro microservicios;
  la administra el equipo, no Cotizaciones).
- No cubre IAM ni redes compartidas del proyecto de curso, más allá de la salida VPC que este
  Service necesita.
- No cubre rollback de Cloud Run más allá de lo ya documentado en
  `docs/evidencias/08-evolucion-e3.md` (límite de rollback del escritor v2 de E3).
