# Evidencia 05 — Pulsar, contratos y ciclo de vida

Estado: **Fase 05 terminada** (Pasos 31–42). Fecha: 2026-09-14 (Bogotá). Entorno: contenedor `dev` (Python 3.12.3, uv 0.10.9, aarch64); `pulsar-client[avro]` 3.13.0 y fastavro 1.12.2; broker Pulsar 4.1.3 standalone y PostgreSQL 17.6 del Compose.

Una instancia es un único proceso FastAPI que consume comandos, publica resultados desde el outbox y atiende HTTP. Hace ACK después del commit y muestra su estado en `/health/ready`. Solo importan `pulsar` los esquemas, los mapeadores de mensajería, el publicador (de forma diferida) y el consumidor (de forma diferida); la prueba de aislamiento lo verifica.

## Lo probado con dobles y lo pendiente con Orquestación real

| Frontera | Probado en esta fase | Pendiente |
|---|---|---|
| `SolicitarCotizacion.v1` (entrada) | Con el **DOBLE DE ORQUESTACION** (`scripts/enviar_peticion.py`) y productores de prueba sobre el mismo `.avsc` | **Integración con Orquestación real**, que debe adoptar `SolicitarCotizacionV1` idéntico (mismo record, orden y tipos); si su esquema difiere hay que coordinar antes de conectar |
| `CotizacionRegistrada.v1` / `CotizacionRechazada.v1` (salida) | Con el **DOBLE LECTOR v1** (`scripts/consumir_resultados.py`) y consumidores SDK en las suscripciones de Orquestación y Seguimiento | Lectores reales de Orquestación y Seguimiento |

**Paquete entregado a Orquestación y Seguimiento:** `docs/contratos/` con los tres `.avsc`, los tres ejemplos con los IDs de 00 §10, `CHECKSUMS.sha256` y un README con tópicos, suscripciones, clave, reglas semánticas de 00 §3–6 y clasificación (comando distribuido y eventos de integración). **Pendiente registrado:** Orquestación debe adoptar el lector provisional.

## Alcance terminado

| Paso | Archivos | Contenido |
|---|---|---|
| 31 | `infraestructura/esquemas/v1/{comandos,eventos}.py` | `SolicitarCotizacionV1` (15 campos), `CotizacionRegistradaV1` (18, `importe_menor` long) y `CotizacionRechazadaV1` (13). Todos con `required=True`, en el orden de 00 y sin namespace. `v1/eventos.py` queda congelado desde el Paso 53. |
| 32 | `docs/contratos/*.avsc`, `*.ejemplo.json`, `README.md`, `CHECKSUMS.sha256` | Los `.avsc` se generaron desde `Record.schema()`. Checksums con `sha256sum`. |
| 33 | `infraestructura/mapeadores_eventos.py` | `ComandoInvalido(ValueError)`. `comando_desde_mensaje` aplica cada regla de 00 §3; el error nombra el campo. `mensaje_registrada` y `mensaje_rechazada` decodifican el documento del outbox y construyen el Record v1 (`version_contrato` 1, `causacion` = `command_id`, categoría tal como llegó), sin consultar catálogo ni base. |
| 34 | `seedwork/infraestructura/ciclos.py` | `EstadoCiclo` y `EstadoComponente` se mudan desde `ciclo_vida.py` y ganan lock y `ultimo_exito`; también `MensajeVenenoso`, `Procesamiento` (`senalar`, `detener(plazo)`) e `iniciar_ciclo`. **Diferencia con Entrada: solo pausa cuando no hubo trabajo.** Error → REINTENTANDO con espera `min(5, 0.2·2^fallos)`; mensaje venenoso → PAUSADO hasta la parada. |
| 35 | `seedwork/infraestructura/publicador_pulsar.py`, `despacho_outbox.py` | `DestinoPulsar` y `PublicadorPulsar`: cliente perezoso, un productor por tópico (sin batching, 1 mensaje pendiente, timeout de envío), clave `id_trabajo`, propiedades `event_id` y `tipo`, verificación de identidad y `cerrar()` idempotente. `DespachadorOutbox` deja de ser frozen y gana `ultimo_error`. |
| 36 | `infraestructura/consumidor_peticiones.py` | Shared, desde `Earliest`, esquema lector, cola configurable, demora de NACK y recepción de 1 s. **ACK solo tras el commit.** Error técnico → NACK y se relanza. `ComandoInvalido`, fallo de decodificación, `ConflictoPeticion` o `ConflictoMensaje` → `MensajeVenenoso` sin ACK ni NACK. `cerrar()` no anula la suscripción. Registra la latencia desde el instante del comando. |
| 37 | `infraestructura/despacho.py` | `iniciar_despacho`: lote de 20. `ErrorPublicacion` si nada se confirmó y hubo error, lo que pone el componente en REINTENTANDO. |
| 38 | `infraestructura/ciclo_vida.py`, `config/bootstrap.py` | `procesar_mensajeria` (sin imports de Pulsar al cargar el módulo): `verificar_destinos` en un hilo; componentes `consumo-peticiones` y `despacho-resultados`; al salir, señala a ambos y los detiene con un presupuesto total de 9 s. En `bootstrap`: `componer_consumidor_peticiones` y `componer_despacho_resultados` (dos destinos con Record v1 y clave `id_trabajo`; propietario `cotizaciones-<uuid>`). |
| 39 | `scripts/{preparar_pulsar,enviar_peticion,consumir_resultados}.py` | Ver "Scripts". |
| 40–41 | `tests/integracion/{pulsar,test_pulsar,test_ciclo_vida}.py`, fixture `laboratorio` | Tópicos únicos por prueba, borrados por la API de administración. |
| 42 | README (mensajería), `docs/contratos/README.md`, CI, esta evidencia | Job `integracion` con Pulsar 4.1.3 mediante `docker run`. |

### Scripts (Paso 39)

- **`preparar_pulsar.py`:**
  - registra los esquemas de resultados creando un productor por tópico;
  - crea la suscripción propia con el esquema lector y las de Orquestación y Seguimiento (con `--historicos-e3`, también `e3-historico-01..05`), todas Shared y desde `Earliest`, sin reiniciar cursores;
  - con `--admin-url`, aplica por tópico cuota de backlog `destination_storage` (50 MiB) y `message_age` (30 min) con `producer_exception`, luego retención (60 min / 100 MiB), y lee todo de vuelta.
- **`enviar_peticion.py` (DOBLE DE ORQUESTACION):**
  - opciones `--categoria`, `--red`, `--tipo-solicitud`, `--id-partner`, `--id-peticion` y `--cantidad`;
  - modos excluyentes `--repetir-comando` (el mensaje idéntico, con el mismo instante), `--nuevo-comando-misma-peticion` y `--contradictoria`;
  - `--salida` escribe un JSONL con los IDs enviados.
- **`consumir_resultados.py` (DOBLE LECTOR v1):**
  - lee con los `.avsc` publicados (`AvroSchema(None, schema_definition=…)`, que resuelve con el esquema del escritor);
  - persiste en SQLite con `event_id` como clave;
  - detecta contenido distinto con el mismo `event_id` y resultados opuestos para una misma petición (código 3);
  - hace ACK tras el commit; `--interrumpir-tras-commit` termina con código 75;
  - no exige `version_contrato` = 1.

## Verificaciones previas (regla 7)

**Firmas de pulsar-client 3.13.0,** inspeccionadas con `inspect.signature`:
- **Confirmado:** `Client(operation_timeout_seconds, connection_timeout_ms, logger)`, `subscribe(consumer_type, schema, receiver_queue_size, negative_ack_redelivery_delay_ms, initial_position)`, `create_producer(send_timeout_millis, max_pending_messages, batching_enabled)`, `send(properties, partition_key)` y `receive(timeout_millis)`.
- **`pulsar.Timeout`** hereda de `PulsarException` → `Exception`.
- **`Message`** tiene `topic_name` y `redelivery_count`.
- **Valores por defecto peligrosos que el servicio fija explícitamente:** `Exclusive`, `Latest` y NACK a 60 s.

**REST de administración de Pulsar 4.1,** sondeado contra el broker con tópicos desechables:
- `POST …/backlogQuota?backlogQuotaType=destination_storage|message_age` → 204;
- `GET …/backlogQuotaMap`;
- `POST …/retention` → 204 solo **después** de la cuota. Antes responde **412**: "Retention Quota must exceed configured backlog quota for topic";
- `GET …/retention` devuelve el valor tras unos instantes, porque las políticas de tópico se aplican de forma asíncrona;
- `GET …/stats` expone `subscriptions[*].msgBacklog`.

## Prueba roja

Con las pruebas unitarias y de contratos escritas y sin implementación, la recolección falló con **8 errores**:

```text
E   ModuleNotFoundError: No module named 'cotizaciones.modulos.cotizaciones.infraestructura.consumidor_peticiones'
E   ModuleNotFoundError: No module named 'cotizaciones.modulos.cotizaciones.infraestructura.esquemas'
E   ModuleNotFoundError: No module named 'cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos'
E   ModuleNotFoundError: No module named 'cotizaciones.seedwork.infraestructura.ciclos'
ERROR tests/api/test_app.py, tests/contratos/test_{comando,resultados}.py,
      tests/unitarias/test_{ciclos,consumidor_peticiones,esquemas,mapeadores_eventos,publicador_pulsar}.py
```

Con la implementación: unitarias, de API y de contratos dieron 357 passed al primer intento. En integración, 14 de 15 pasaron al primer intento; la falla (`test_caida_tras_el_envio_y_antes_de_marcar_republica_el_mismo_event_id`) se explica en "Decisiones y desviaciones". Después hubo correcciones de lint y tipos (2 E501, formato de 3 archivos, 3 errores de mypy en pruebas).

Las pruebas de integración de Pulsar se escribieron después del código de composición. Su valor es verificar el proceso completo con infraestructura real, no marcar un rojo.

## Pruebas

| Archivo | Pruebas | Qué cubre |
|---|---|---|
| `tests/unitarias/test_esquemas.py` | 4 | Nombre, orden, tipos, sin namespace ni defaults; 15, 18 y 13 campos |
| `tests/contratos/test_comando.py` | 4 | Record igual al `.avsc`; claves del ejemplo en orden; bytes leídos con fastavro y el `.avsc` iguales al ejemplo y deterministas; el ejemplo se traduce al comando propio de la F1 |
| `tests/contratos/test_resultados.py` | 8 | Lo mismo para propuesta y rechazo, con los bytes producidos por el mapeador desde el outbox; checksums; nombres de record distintos |
| `tests/unitarias/test_mapeadores_eventos.py` | 35 | Traducción válida; `version_contrato` 2 aceptada; **24 reglas violadas**, cada una con su campo; objeto sin campos; propuesta y rechazo a Record v1; categoría tal como llegó; homologada; documento del tipo equivocado |
| `tests/unitarias/test_ciclos.py` | 10 | Con trabajo no pausa (≥ 50 pasos en menos de 1 s con pausa de 5 s); sin trabajo pausa; INICIANDO → REINTENTANDO → OPERANDO; venenoso → PAUSADO sin volver a llamar al paso; `detener` en menos de 1 s durante la espera; `cerrar` exactamente una vez; hilo con nombre y no daemon; `TimeoutError` con plazo vencido |
| `tests/unitarias/test_publicador_pulsar.py` | 10 | Cliente perezoso; un productor por tópico reutilizado; clave y propiedades; destino desconocido; identidad incoherente; error de envío; fallo al crear el productor cierra el cliente; `cerrar` idempotente; `ultimo_error` del despachador se registra y se limpia |
| `tests/unitarias/test_consumidor_peticiones.py` | 18 | ACK solo tras procesar; NACK ante `CatalogoNoDisponible` y error SQL; inválido, bytes corruptos y conflictos → venenoso sin ACK ni NACK; timeout → falso; parámetros de suscripción; fallo al suscribir cierra el cliente; `cerrar` sin `unsubscribe`; retardo sintético; configuración inválida |
| `tests/integracion/test_pulsar.py` | 8 | Los 8 casos del Paso 40 (tabla siguiente) |
| `tests/integracion/test_ciclo_vida.py` | 7 | Los 7 casos del Paso 41 (tabla siguiente) |

Nuevas: 104. Suite completa: **429 passed** en 25,6 s.

### Paso 40: integración real con Pulsar

| # | Caso | Resultado |
|---|---|---|
| 1 | Comando Avro real enviado por el **DOBLE DE ORQUESTACION** (proceso aparte) | Fila, salida enviada y resultado leído en `orquestacion-cotizacion-registrada-v1`: `causacion` = `command_id`, proveedor `a101`, 15000000, propiedades `event_id`/`tipo`, `partition_key` = `id_trabajo` |
| 2 | Propuesta y rechazo, cada uno una vez, en dos suscripciones independientes | `preparar_pulsar.py --admin-url` (3 políticas leídas de vuelta con retención 60); el DOBLE LECTOR v1 persiste 2 en SQLite con las suscripciones de Orquestación; las de Seguimiento reciben exactamente un mensaje por tópico |
| 3 | Caída después del commit y antes del ACK | Consumo manual, handler SQL, `close()` sin ACK (backlog 1); al iniciar el servicio llega la reentrega, se hace ACK (backlog 0) y queda 1/1/1 |
| 4 | Caída tras el envío y antes de marcar la salida | Se republica con el mismo `event_id`; el DOBLE LECTOR v1 registra `persistido` `[true, false]` y 1 fila |
| 5 | Broker inaccesible (`pulsar://127.0.0.1:1`) | Cotización confirmada, salida pendiente con `ultimo_error`, componente REINTENTANDO (`ErrorPublicacion`); con el broker correcto se publica |
| 6 | Catálogo ausente | NACK, consumo REINTENTANDO con `CatalogoNoDisponible`, sin fila ni inbox; tras cargar el catálogo se procesa solo y vuelve a OPERANDO; backlog 0 |
| 7 | Mensaje inválido (`tipo_red` = `OTRA_RED`) | Consumo PAUSADO; `/health/ready` 503 `mensajeria_no_operativa` con el `command_id` y el motivo; el despacho sigue OPERANDO y publica; live 200; el mensaje queda sin ACK (backlog 1) |
| 8 | Servicio detenido y productor activo | 5 envíos, backlog 5, ninguna fila; al arrancar, 5 cotizaciones, 5 salidas enviadas, backlog 0 y 0 marcas sin efecto |

### Paso 41: composición del proceso

| # | Caso | Resultado |
|---|---|---|
| 1 | Iniciar y cerrar el lifespan dos veces | Siempre exactamente los hilos `consumo-peticiones` y `despacho-resultados`; ninguno vivo al salir |
| 2 | Mensajes sin HTTP | Un mensaje enviado con el lifespan activo y ninguna petición HTTP → fila y salida enviada |
| 3 | Live mientras `receive` espera | 3 × `GET /health/live` en menos de 0,5 s; ready 200 |
| 4 | Parada durante la espera | Menos de 10 s (≈ 1 s) y sin hilos vivos |
| 5 | Parada durante una transacción (confirmación ralentizada 1,5 s) | El cierre espera el paso en curso: commit y después ACK (fila 1, backlog 0); cierre en menos de 10 s |
| 6 | Reinicio tras commit sin ACK | Un `CaidaSimulada(BaseException)` después del commit mata el hilo como una caída (backlog 1); otra app hace ACK de la reentrega sin duplicar (1/1/1) |
| 7 | Dos apps con la misma base y la misma suscripción | 20 comandos → 20 cotizaciones, 20 salidas enviadas, 20 marcas, 0 marcas sin efecto, backlog 0 |

## Comandos ejecutados y resultado

| Comando | Resultado |
|---|---|
| `uv run --locked pytest tests -q -s --tb=short` | **429 passed**, 1 warning (Starlette/anyio, de terceros) |
| `uv run --locked ruff check .` / `ruff format --check .` | All checks passed / 134 files already formatted |
| `uv run --locked mypy src tests scripts migraciones` | Success: no issues found in 117 source files |
| `uv run --locked python scripts/verify_distribution.py` | `Wheel instalado importado fuera del arbol fuente: …/site-packages/cotizaciones/__init__.py`. Ahora también comprueba los 3 Records (sin namespace), los mapeadores, el consumidor, el publicador, los ciclos y el despacho |
| `git diff --check` | Sin salida, exit 0 |
| YAML del CI | `verificacion-unitaria`: 8 pasos; `integracion`: 7 pasos con servicio `postgres` y Pulsar mediante `docker run` |
| `sha256sum *.avsc *.ejemplo.json` | `CHECKSUMS.sha256` con 6 entradas, verificado por `tests/contratos` |

### Recorrido manual (Paso 42) sobre la base local y los tópicos por defecto

Con `COTIZACIONES_DATABASE_URL=…@postgres:5432/cotizaciones` y `COTIZACIONES_PULSAR_URL=pulsar://pulsar:6650`:

| Paso | Resultado |
|---|---|
| `preparar_pulsar.py --admin-url http://pulsar:8080` | 2 esquemas registrados; 5 suscripciones (`cotizaciones-peticiones-v1`, `orquestacion-cotizacion-registrada-v1`, `seguimiento-cotizacion-registrada`, `orquestacion-cotizacion-rechazada-v1`, `seguimiento-cotizacion-rechazada-v1`); en los 3 tópicos, retención `{60 min, 100 MB}` y cuotas `destination_storage` 52428800 y `message_age` 1800 s, leídas de vuelta |
| `uvicorn cotizaciones.api.app:create_app --factory` | `/health/live` 200; `/health/ready` 200 `listo`, con `consumo-peticiones` y `despacho-resultados` en OPERANDO y su `ultimo_exito` |
| DOBLE DE ORQUESTACION | `enviado original command_id=4066cd32-8f2b-45e4-926e-256514da488e id_peticion=cf4408ed-072b-4c42-b2a6-d6811cc84cee categoria=plomeria` |
| DOBLE LECTOR v1, `--solo registrada --limite 2` | `event_id` 871675c2… (la F1 que estaba pendiente desde la Fase 04) y 54b5cc78… (la nueva), ambas `persistido: true`, exit 0 |
| DOBLE LECTOR v1, `--solo rechazada --limite 1` | `event_id` fbda31b2… (la F5 de la Fase 04), `persistido: true`, exit 0 |
| `psql` | 3 cotizaciones, 3 marcas de inbox, outbox con 3 enviadas y 0 pendientes |
| `SIGTERM` al proceso uvicorn | **Cierre en 1,01 s**: `Shutting down` → `Application shutdown complete` → `Finished server process` |

Las 2 salidas que la Fase 04 dejó pendientes se publicaron al arrancar el servicio, con el `event_id` y el contenido guardados en el outbox.

## Decisiones y desviaciones

- **`EstadoCiclo` y `EstadoComponente` pasan a `seedwork/infraestructura/ciclos.py`,** como anticipó la evidencia 01. `ciclo_vida.py` conserva `EstadoMensajeria` y el ensamblaje; sin fachadas de reexportación. `test_app.py` importa ahora desde `ciclos`, y su resumen incluye `ultimo_exito`.
- **Presupuesto de cierre:** 9 s compartidos entre los dos ciclos (recepción de 1 s, operación Pulsar de 3 s, sentencia SQL de 3 s).
- **`preparar_pulsar.py`:** aplica la cuota antes que la retención (el broker exige retención > cuota) y valida en los argumentos que `--retencion-mib` supere `--backlog-mib`.
- **Logs del cliente C++ en los dobles:** `enviar_peticion.py` y `consumir_resultados.py` pasan `logger=` a `pulsar.Client`. Así los logs INFO del cliente van al logging de Python (stderr, desde WARNING) y stdout queda como JSONL limpio. Esa era la causa de la única falla inicial de integración: la prueba 4 parseaba stdout. `preparar_pulsar.py` mantiene los logs del cliente en stdout; las pruebas filtran las líneas JSON.
- **Tipo de las pruebas del lector:** el DOBLE LECTOR v1 usa los `.avsc` y no los Records del productor. Así su independencia del paquete es real.
- **CI:** el job `integracion-postgres` se renombra `integracion`, porque ahora incluye Pulsar.
- **Recorrido manual:** el primer intento pasó mal las variables por dos errores míos. zsh no separa `$E` en palabras, así que uvicorn arrancó sin base. Luego un heredoc con `docker compose exec` sin `-T` perdió el stdin. Ambos se corrigieron (arreglo zsh, `-T` y `< /dev/null`) y el recorrido válido es el documentado.

## Limitaciones

- **Orquestación real:** no existe todavía. Todo lo de entrada se probó con el doble y con productores de prueba del mismo `.avsc`.
- **Logs INFO de la aplicación:** uvicorn no configura el logger `cotizaciones`, así que las líneas INFO del consumidor (`Peticion …: cotizacion …, nueva=…, latencia …`) no aparecen en su salida; los errores sí. Se resuelve junto con la imagen (Fase 09). Las métricas de E4/E8 salen de la base (`registrada_en − instante_comando`, Paso 47), no de los logs.
- **`ultimo_error` del despacho con varias réplicas:** sigue la regla del plan (se limpia solo al confirmar). Si una salida que falló aquí la publica **otra** réplica, esta sigue en REINTENTANDO hasta confirmar algo propio. No afecta a la corrección, solo a la lectura de readiness con varias réplicas; se revisará en la Fase 07 (E4).
- **Mensaje venenoso:** bloquea el consumo de esa instancia hasta que un operador actúe (limitación aceptada de la POC). Con varias réplicas, el mismo mensaje puede pausarlas por turnos.
- **CI:** no se ha ejecutado en GitHub (no hay push); la sintaxis y los comandos se validaron localmente.
- **Configuración pendiente:** `connect_timeout` de PostgreSQL (evidencia 01).

## Siguiente dependencia

Fase 06 (Pasos 43–46): consultas HTTP (`GET /cotizaciones/{id}` y `GET /cotizaciones`) sobre el estado relacional propio, contrato `consultas.md` y `openapi.json` exportado, y la prueba de integración comando → persistencia → consulta HTTP.
