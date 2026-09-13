# Fase 05 — Pulsar, contratos y ciclo de vida (Pasos 31–42)

Corresponde a `planes-otros-microservicios/cotizaciones/05-pulsar-contratos.md` y a la sección "Ciclo de vida integrado" de `02-base-de-implementacion.md`. Resultado: una instancia es un único proceso FastAPI que consume comandos, publica resultados desde el outbox y atiende HTTP, con ACK después del commit y estado visible en readiness. Solo los módulos de `esquemas/`, los mapeadores de mensajería, el consumidor y el publicador importan `pulsar`.

---

## Paso 31 — Records Avro v1

**Archivos:** `modulos/cotizaciones/infraestructura/esquemas/{__init__,v1/__init__,v1/comandos,v1/eventos}.py`, `tests/unitarias/test_esquemas.py`.

- `v1/comandos.py`: `SolicitarCotizacionV1` con los 15 campos de [00 §3](00-contratos-y-datos.md), en ese orden y todos obligatorios.
- `v1/eventos.py`: `CotizacionRegistradaV1` (18 campos de 00 §4, `importe_menor` de tipo long) y `CotizacionRechazadaV1` (13 campos de 00 §5). **Este archivo queda congelado desde el Paso 53.**

**Prueba:** el esquema generado por el SDK tiene el nombre de record, el orden de campos y los tipos de 00, y no incluye namespace.

## Paso 32 — Contratos exportados

**Archivos:** `docs/contratos/{solicitar-cotizacion-v1,cotizacion-registrada-v1,cotizacion-rechazada-v1}.avsc`, los tres `*.ejemplo.json` (IDs de 00 §10), `docs/contratos/README.md`, `docs/contratos/CHECKSUMS.sha256`, `tests/contratos/test_comando.py`, `tests/contratos/test_resultados.py`.

- Cada `.avsc` es la salida exacta del esquema del Record.
- El README del contrato documenta: tópicos, suscripciones, clave, reglas y la clasificación justificada (el comando es distribuido porque pide una acción que puede fallar; los resultados son eventos de integración con la carga necesaria para el efecto aguas abajo, sin llamadas síncronas al productor). Declara que `SolicitarCotizacion.v1` es una **propuesta lectora** pendiente de adopción por Orquestación.

**Pruebas (patrón de `tests/contratos/test_solicitud_lista.py` de Entrada):** el esquema del Record es igual al `.avsc`; las claves del ejemplo coinciden con los campos; los bytes producidos por el mapeador, leídos con fastavro y el `.avsc`, son iguales al ejemplo; codificar dos veces produce bytes idénticos.

## Paso 33 — Mapeadores de mensajería

**Archivo:** `modulos/cotizaciones/infraestructura/mapeadores_eventos.py` (separado de los mapeadores SQL). **Pruebas:** `tests/unitarias/test_mapeadores_eventos.py`.

- Excepción `ComandoInvalido` (subclase de `ValueError`).
- `comando_desde_mensaje(record)`: aplica todas las reglas de 00 §3 y construye `ProcesarPeticionCotizacion` con tipos propios. Cualquier fallo lanza `ComandoInvalido` con el campo y el motivo.
- `mensaje_registrada(documento)` y `mensaje_rechazada(documento)`: decodifican el documento del outbox con la serialización del Paso 26, exigen el tipo de evento correcto y construyen el Record v1 (`version_contrato` 1, `causacion` = `id_comando`, `categoria` tal como llegó). Nunca consultan catálogo ni base.

**Pruebas:** traducción válida; un caso por regla violada; ida y vuelta evento → documento → Record con los valores esperados; documento del tipo equivocado falla.

## Paso 34 — Ciclos supervisados

**Archivo:** `seedwork/infraestructura/ciclos.py` (adaptación de Entrada). **Pruebas:** `tests/unitarias/test_ciclos.py`.

- `EstadoComponente`: nombre, estado (`INICIANDO`, `OPERANDO`, `REINTENTANDO`, `PAUSADO`, `DETENIDO`), último error, ID y motivo de pausa e instante del último éxito. Protegido por un lock porque lo leen el hilo HTTP y el hilo del ciclo. `EstadoMensajeria` (Paso 7) agrupa estos componentes.
- Excepción `MensajeVenenoso`, con el ID del mensaje y el motivo.
- `iniciar_ciclo(ejecutar_paso, nombre, estado, pausa_inactiva=0.2, espera_maxima_error=5.0, cerrar)` devuelve `Procesamiento` (hilo no daemon + señal de parada). **Diferencia clave con Entrada: solo se pausa cuando no hubo trabajo.**

```text
estado ← INICIANDO; fallos ← 0
mientras no se pidió parada:
  intentar:
    hubo_trabajo ← ejecutar_paso()
    estado ← OPERANDO; fallos ← 0
    si no hubo_trabajo: esperar(pausa_inactiva)          // interrumpible por la parada
  ante MensajeVenenoso e:
    estado ← PAUSADO(e.id, e.motivo); registrar en log con ID y motivo
    esperar hasta que se pida parada; salir               // no más recepciones en esta instancia
  ante otro error e:
    estado ← REINTENTANDO(e); registrar en log; fallos ← fallos + 1
    esperar(mínimo(espera_maxima_error, 0.2 × 2^fallos))  // espera acotada, sin bucle rápido
al terminar: cerrar(); estado ← DETENIDO
```

- `Procesamiento.detener(plazo=8)`: señala la parada y espera el hilo; si no termina en el plazo lanza `TimeoutError`.

**Pruebas:** sin trabajo se pausa y con trabajo no; un error pasa a REINTENTANDO y el siguiente éxito vuelve a OPERANDO; un mensaje venenoso deja el ciclo en PAUSADO y no vuelve a llamar al paso; `detener` termina en menos de 1 s durante la espera; `cerrar` se llama exactamente una vez.

## Paso 35 — Publicador enrutado por destino

**Archivo:** `seedwork/infraestructura/publicador_pulsar.py` (adaptación de Entrada). **Pruebas:** `tests/unitarias/test_publicador_pulsar.py`.

- `DestinoPulsar`: tópico, esquema, función de conversión documento → Record y función de clave (devuelve `id_trabajo`).
- `PublicadorPulsar(url, destinos, timeout_segundos, crear_cliente)`: el cliente se crea al primer uso (nunca al importar ni al construir) y hay un productor por tópico, sin batching, con un solo mensaje pendiente y timeout de envío. `crear_cliente` es inyectable para las pruebas.
- `publicar(publicacion)`: busca el destino (si es desconocido, `ValueError`), convierte, exige que el `event_id` del Record sea igual al `id_evento` de la publicación, envía con clave de partición y propiedades `event_id` y `tipo`, y devuelve verdadero tras el acuse del broker. `cerrar()` es idempotente.
- `DespachadorOutbox`: añadir el atributo `ultimo_error`, que se actualiza en cada fallo y se limpia en cada confirmación.

**Pruebas con cliente falso:** se crea un productor por tópico y se reutiliza; destino desconocido falla; identidad incoherente falla; se usan la clave y las propiedades correctas; tras `cerrar`, el siguiente envío crea un cliente nuevo.

## Paso 36 — Consumidor de peticiones

**Archivo:** `modulos/cotizaciones/infraestructura/consumidor_peticiones.py`. **Pruebas:** `tests/unitarias/test_consumidor_peticiones.py`.

`ConsumidorPeticiones` recibe URL, tópico, suscripción, la función `procesar` (el handler), tamaño de cola, demora de NACK, timeout, retardo de laboratorio y `crear_cliente`. `abrir()` se suscribe en modo Shared, desde el inicio, con el esquema `SolicitarCotizacionV1`, el tamaño de cola configurado y la demora de NACK. Si falla, cierra el cliente y propaga el error. `cerrar()` cierra el cliente **sin** anular la suscripción.

```text
procesar_siguiente():
  abrir()
  mensaje ← recibir(timeout 1000 ms)          // si vence el timeout: devolver falso (no es error)
  id ← propiedad command_id del mensaje, o su MessageId
  intentar comando ← comando_desde_mensaje(valor decodificado)
    ante ComandoInvalido o error de decodificación → lanzar MensajeVenenoso(id, motivo)   // sin ACK ni NACK
  si retardo_laboratorio > 0: esperar ese retardo (etiquetado como sintético)
  intentar resultado ← procesar(comando)
    ante ConflictoPeticion o ConflictoMensaje → lanzar MensajeVenenoso(id, motivo)        // sin ACK
    ante cualquier otro error → NACK(mensaje); relanzar                                    // técnico: se reentrega
  ACK(mensaje)                                 // solo después del commit del handler
  registrar en log id_peticion, id_cotizacion, nueva y latencia desde el instante del comando
  devolver verdadero
```

**Pruebas con consumidor falso:** ACK solo después de un procesamiento exitoso; NACK ante `CatalogoNoDisponible` o error SQL; ni ACK ni NACK ante mensaje inválido o conflicto; un timeout devuelve falso.

## Paso 37 — Despacho de resultados

**Archivo:** `src/cotizaciones/infraestructura/despacho.py`.

`iniciar_despacho(despachador, estado, cerrar)` inicia un ciclo cuyo paso es:

```text
confirmadas ← despachador.despachar_lote(20)
si confirmadas = 0 y despachador.ultimo_error existe: lanzar ErrorPublicacion(ultimo_error)   // readiness: REINTENTANDO
devolver confirmadas > 0
```

La salida fallida ya quedó reprogramada en el outbox; el error solo la hace visible.

## Paso 38 — Ciclo de vida integrado en lifespan

**Archivos:** `infraestructura/ciclo_vida.py` (completar), `config/bootstrap.py` (`componer_consumidor_peticiones(base, configuracion)` y `componer_despacho_resultados(base, configuracion)`).

- `componer_despacho_resultados` crea el `PublicadorPulsar` con los dos destinos de 00 §7 (tópico, esquema v1, mapeador y clave), un `RepositorioOutbox` limitado a los destinos admitidos y un `DespachadorOutbox` con propietario `cotizaciones-<uuid>`. Devuelve el despachador y la función de cierre del publicador.
- `procesar_mensajeria(base, configuracion)`:

```text
en un hilo: verificar_destinos(base)       // destinos desconocidos → el arranque falla
estado ← EstadoMensajeria con componentes "consumo-peticiones" y "despacho-resultados"
iniciar ciclo de consumo  (paso = consumidor.procesar_siguiente, cerrar = consumidor.cerrar)
iniciar ciclo de despacho (paso del Paso 37, cerrar = cierre del publicador)
entregar estado a la app
al salir: señalar parada a ambos; en un hilo, detener cada uno (presupuesto total < 10 s)
```

- Reglas de cierre: nunca hacer ACK ni marcar el outbox como parte del apagado; nunca anular suscripciones; liberar la base solo después de detener ambos ciclos (lo hace `create_app`). Un Pulsar caído al arrancar no impide levantar la API: el componente queda en REINTENTANDO.

## Paso 39 — Scripts de Pulsar y dobles etiquetados

**Archivos:** `scripts/preparar_pulsar.py`, `scripts/enviar_peticion.py`, `scripts/consumir_resultados.py`.

- `preparar_pulsar.py`: registra los esquemas creando y cerrando un productor por cada tópico de resultado; crea la suscripción propia con el esquema lector (Shared, desde el inicio) y crea las suscripciones consumidoras de 00 §1 (las `e3-historico-*` solo con `--historicos-e3`). Con `--admin-url`, aplica por tópico la cuota de backlog y la retención (valores por argumento; por defecto los de Entrada: 50 MiB/30 min con rechazo al productor y retención 1 h/100 MiB) y los lee de vuelta. Nunca reinicia cursores. Antes de implementar las llamadas administrativas, verificar las rutas REST en la documentación de Pulsar 4.1.
- `enviar_peticion.py`: **DOBLE DE ORQUESTACIÓN**, así rotulado en la ayuda y en cada salida. Envía `SolicitarCotizacionV1` con `--categoria`, `--red`, `--id-partner`, `--cantidad` y los modos `--repetir-comando`, `--nuevo-comando-misma-peticion` y `--contradictoria`. Escribe en `--salida` un JSONL con los IDs enviados, que usa la reconciliación.
- `consumir_resultados.py`: **DOBLE LECTOR v1**. Lee uno o ambos tópicos de resultado con la suscripción indicada, persiste en SQLite (`event_id` como clave, contenido normalizado), detecta contradicciones y hace ACK después del commit. Tiene `--interrumpir-tras-commit` (termina antes del ACK). Es tolerante: no exige `version_contrato` = 1. Sirve también como lector histórico congelado en E3.

## Paso 40 — Integración real con Pulsar

**Archivos:** `tests/integracion/pulsar.py` (tópicos únicos por prueba y limpieza por la API de administración, como el fixture de Entrada), `tests/integracion/test_pulsar.py`.

**Pruebas:**
1. Un comando Avro real enviado por el doble produce una fila, una salida confirmada y un resultado decodificable leído con la suscripción de Orquestación.
2. La propuesta y el rechazo llegan una sola vez a su tópico respectivo y los reciben dos suscripciones independientes (Orquestación y Seguimiento).
3. Caída después del commit y antes del ACK: se consume con la suscripción del servicio, se ejecuta el handler SQL y se cierra sin ACK. Al iniciar el servicio llega la reentrega, se hace ACK y no aparece otra cotización ni otra salida.
4. Caída después del envío y antes de marcar la salida: se republica con el mismo `event_id` y el lector doble registra un solo efecto.
5. Publicador contra un broker inaccesible: la cotización se confirma, la salida queda pendiente con `ultimo_error` y el componente pasa a REINTENTANDO; con el broker correcto, se publica.
6. Catálogo ausente: el mensaje recibe NACK y no deja fila; tras cargar el catálogo se procesa solo.
7. Mensaje inválido: el consumo queda PAUSADO, readiness responde 503 con el ID y el despacho sigue operando.
8. Con Cotizaciones detenido, el doble productor sigue enviando y el backlog crece: la caída no afecta al productor.

## Paso 41 — Pruebas de composición del proceso

**Archivo:** `tests/integracion/test_ciclo_vida.py`.

**Pruebas:**
1. Iniciar y cerrar el lifespan dos veces no deja hilos duplicados ni vivos (se cuentan por nombre).
2. Los mensajes se procesan sin ninguna petición HTTP.
3. `GET /health/live` responde mientras el consumidor espera en `receive`.
4. La parada durante la espera termina en menos de 10 s.
5. La parada durante una transacción en curso (handler ralentizado en la prueba) nunca produce ACK sin commit.
6. Reiniciar después de un commit sin ACK converge.
7. Dos apps con la misma base y la misma suscripción procesan N mensajes y dejan una cotización por petición.

## Paso 42 — Entrega de contratos, CI y evidencia

**Archivos:** README (sección de mensajería), ampliación de `.github/workflows/ci.yml`, `docs/evidencias/05-pulsar.md`.

- Paquete para Orquestación: `.avsc`, ejemplos, checksums y reglas de 00 §3–6. Registrar como **pendiente** que Orquestación adopte `SolicitarCotizacionV1` idéntico. Si su esquema difiere, detenerse y coordinar: un nombre o un orden distinto produce un esquema incompatible en el tópico.
- CI: el job de integración levanta Pulsar 4.1.3 standalone con un paso `docker run` (los contenedores de servicio de Actions no aceptan comando) y ejecuta toda la carpeta `tests/integracion`.
- La evidencia 05 separa lo probado con el doble de lo probado con Orquestación real.

**Verificación:** verificación estándar con PostgreSQL y Pulsar arriba; arranque manual con `uvicorn` y recorrido doble → fila → resultado leído por `consumir_resultados.py`.
