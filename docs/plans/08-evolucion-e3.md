# Fase 08 — Evolución E3: `duracion_estimada_minutos` (Pasos 53–59)

Corresponde a las secciones E3 de `cotizaciones/05` y `08`, `seguimiento/07` y `03-integracion-experimentos-y-entrega.md §7`. Seguimiento lidera el experimento; Cotizaciones es dueño del escritor y del dato. La revisión 2 añade un único campo opcional en el **mismo** tópico, con el **mismo** nombre de record y el **mismo** `tipo`. El rechazo no cambia.

---

## Paso 53 — Congelar v1 (PUNTO DE CONTROL)

1. Pedir autorización al usuario para hacer commit y crear el tag `cotizaciones-v1.0.0`.
2. Si el despliegue será en Cloud Run, ejecutar primero los Pasos 60–61 sobre ese commit y etiquetar la imagen `cotizaciones:v1`.
3. Exportar `docs/contratos/fixtures/cotizacion-registrada-v1.bin` (bytes Avro del ejemplo) y registrar los SHA-256 del `.avsc` v1, del wheel y de la imagen.
4. Coordinar con Seguimiento y Orquestación que sus lectores v1 y los cinco dobles (`consumir_resultados.py` del tag v1, suscripciones `e3-historico-01` a `05`) quedan congelados **antes** de cualquier cambio.
5. Desde aquí, `esquemas/v1/eventos.py` no se modifica.

## Paso 54 — Migración aditiva y dominio

**Archivos:** `migraciones/versions/0002_duracion_estimada.py`; actualización de `objetos_valor.py`, `eventos.py`, `entidades.py`, `orm.py`, `mapeadores.py`, `serializacion.py` y `repositorios.py`.

- La migración añade `duracion_estimada_minutos` (entero nulo, con restricción "nulo o > 0") a `ofertas_catalogo` y a `cotizaciones`. El downgrade la elimina. Se aplica **antes** de cambiar binarios.
- `OfertaCatalogo` y `CotizacionRegistrada` incorporan la duración opcional: entero estricto > 0 o ausente (nunca 0 ni booleano). El agregado copia la duración de la oferta elegida, y así queda persistida antes del outbox.
- Los documentos de evento pasan a `version_formato` 2 con el campo de duración. El decodificador acepta el formato 1 (duración ausente = desconocida) y el 2.

**Pruebas:** filas v1 se leen con duración nula; ida y vuelta con 30, 90 y nulo; 0, negativos y booleanos fallan.

## Paso 55 — Record revisión 2

**Archivos:** `esquemas/v2/{__init__,eventos}.py`, `docs/contratos/cotizacion-registrada-v1.rev2.avsc`, `cotizacion-registrada-v1.rev2.ejemplo.json`, `fixtures/cotizacion-registrada-v1.rev2.bin`, `tests/contratos/test_resultados_rev2.py`.

- `CotizacionRegistradaV1` en `v2/eventos.py`: campos 1–18 idénticos a v1 más el campo 19, unión de nulo y entero **con default null**, al final.
- Con lo registrado en el Paso 2, confirmar que el SDK emite el default y que decodifica la ausencia como `None`. Si no lo hace, crear en ese módulo un tipo entero opcional que devuelva `None` como default, igual que `BooleanOpcional` de Entrada, y citar el código fuente del SDK.

**Pruebas:** el esquema es igual al archivo rev2; difiere del v1 únicamente en el campo añadido con default null.

## Paso 56 — Escritor v2, catálogo v2 y consulta

**Archivos:** `mapeadores_eventos.py`, `config/bootstrap.py` (el destino de la propuesta usa el Record v2), `aplicacion/consultas.py` y el repositorio de lectura (campo nuevo), `docs/contratos/openapi.json` regenerado, `datos/catalogos/catalogo-v2.json`.

- `mensaje_registrada` construye el Record v2 con `version_contrato` 2 y la duración **leída del documento guardado**, nunca del catálogo.
- `catalogo-v2.json` es la versión 2, con las duraciones de 00 §9. Se carga con `--activar` sin tocar la versión 1.
- Recomendación operativa: drenar el outbox de propuestas antes de cambiar el binario y registrar ese punto. Si quedara un documento de formato 1 pendiente, el escritor v2 lo publica con duración nula (los lectores lo tratan como el mismo hecho).

**Pruebas (F8):** peticiones nuevas después de activar v2 publican 30, 90 y nulo. Una petición resuelta antes del cambio conserva su resultado y su evento original: su reentrega no genera otro evento. Nunca se republican hechos históricos.

## Paso 57 — Compatibilidad en registro y broker

**Archivos:** `scripts/preparar_pulsar.py` (opción `--compatibilidad FULL_TRANSITIVE`, que la aplica al tópico de propuestas y la lee de vuelta; verificar la API de administración de Pulsar 4.1), `tests/contratos/test_compatibilidad.py`, `tests/integracion/test_compatibilidad_broker.py`.

**Pruebas:**
1. Sin red, con fastavro: escritor v1 → lector v2 da duración nula; escritor v2 → lector v1 ignora el campo; ambas direcciones con los fixtures binarios.
2. Con broker, en un tópico de control aislado configurado FULL_TRANSITIVE: se registra v1, se acepta v2 y se **rechaza** un cambio incompatible (por ejemplo, cambiar el tipo de `importe_menor` o añadir un campo obligatorio sin default).
3. En el tópico real, el lector v1 congelado sigue consumiendo mensajes v2.

**CI:** job `compatibilidad` que ejecuta solo estas pruebas contra Pulsar standalone. Se mide su duración (objetivo < 60 s).

## Paso 58 — Participación de Cotizaciones en los brazos

**Archivo:** `docs/experimentos/e3-cotizaciones.md`.

| Brazo | Qué hace Cotizaciones |
|---|---|
| 1. Referencia | Escritor v1 activo; genera ofertas por el recorrido normal |
| 2. Productor primero | Migración 0002 y luego escritor v2, con los lectores antiguos intactos |
| 3. Consumidor primero | Mantiene escritor v1 mientras Seguimiento v2 se despliega; luego escritor v2 |
| 4. Histórico | Nada: el lector v2 de Seguimiento lee v1 retenido. Verificar que no se republicó |
| 5. Reversión | Drenar el outbox de propuestas (0 pendientes con `inspeccionar_outbox.py`), registrar el punto y volver a la imagen v1 sobre la base migrada; las ofertas nuevas salen sin duración y las anteriores conservan la suya |
| 6. Control incompatible | Prueba 2 del Paso 57 |

Medidas de Cotizaciones: esfuerzo real en horas-persona (objetivo ≤ 2 días-persona), cero hechos históricos republicados (conteo de salidas antes y después) y duración del job de compatibilidad.

## Paso 59 — Evidencia 08 y entrega a Seguimiento

**Archivo:** `docs/evidencias/08-evolucion-e3.md`.

Entregar los esquemas rev1/rev2, los fixtures, los IDs de las peticiones F8 y los hashes de imágenes y artefactos. Declarar qué lectores son dobles y cuál es real (Orquestación), y el límite de rollback: no se recodifican salidas v2 con un mapeador v1.
