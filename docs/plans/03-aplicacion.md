# Fase 03 — Caso de uso idempotente (Pasos 17–21)

Corresponde a `planes-otros-microservicios/cotizaciones/03-casos-uso-idempotencia.md`. Resultado: `ProcesarPeticionHandler` probado con dobles en memoria. Aún no hay durabilidad, consumidor automático ni Pulsar. Ruta base: `src/cotizaciones/modulos/cotizaciones/aplicacion/`.

---

## Paso 17 — Seedwork de aplicación

**Archivos:** `src/cotizaciones/seedwork/aplicacion/{identificadores,reloj,reintentos,unidad_trabajo,publicacion}.py`, `src/cotizaciones/seedwork/infraestructura/{__init__,reloj,identificadores}.py`.

**Acción:** copiar de Entrada los puertos `GeneradorIdentificadores` y `Reloj`, el decorador `reintentar_colision` (3 intentos ante `ColisionPersistencia`), `Publicacion` y `Publicador`, y los adaptadores `RelojActual` (UTC) e `IdentificadoresAleatorios` (uuid4).

**Adaptación del protocolo `UnidadTrabajo`:** conservar la gestión de contexto, `confirmar`, `revertir` y `registrar_salida(evento)`. **Quitar `preparar_entrada`**: la marca de consumo de Cotizaciones es de un comando externo, no de un evento de dominio, y se declara en el puerto del módulo (Paso 19).

Agregar a `seedwork/aplicacion/excepciones.py` la excepción `ConflictoMensaje` (subclase de `ValueError`): mismo ID de mensaje con distinto contenido.

## Paso 18 — Comando interno y errores de aplicación

**Archivos:** `aplicacion/__init__.py`, `aplicacion/comandos.py`, `aplicacion/excepciones.py`.

**Contenido:**
- `ProcesarPeticionCotizacion`: dataclass inmutable con `origen` (`OrigenComando`) y `datos` (`DatosPeticion`). Es el comando **propio** que produce el traductor de mensajería (Pasos 33 y 36). Nunca transporta un Record Avro ni una Session.
- `ConflictoPeticion` (subclase de `ValueError`): la `id_peticion` ya fue resuelta con otros datos de negocio.

## Paso 19 — Puerto de unidad de trabajo del módulo

**Archivo:** `aplicacion/unidad_trabajo.py`.

**Contenido:** protocolo `UnidadTrabajoCotizaciones`, que extiende `UnidadTrabajo` con:
- los atributos `cotizaciones` (`RepositorioCotizaciones`) y `catalogos` (`RepositorioCatalogo`);
- el método `registrar_recepcion(consumidor, comando)`, que devuelve verdadero si la marca `(consumidor, id_comando)` es nueva, falso si ya existía con el mismo contenido, y lanza `ConflictoMensaje` si existía con otro contenido. Participa de la misma transacción que el efecto.

## Paso 20 — Handler `ProcesarPeticionHandler`

**Archivos:** `aplicacion/handlers/__init__.py`, `aplicacion/handlers/procesar_peticion.py`, `config/bootstrap.py`.

**Contenido del handler:** dataclass inmutable con el atributo de clase `consumidor = "cotizaciones.procesar_peticion"` y los campos `crear_unidad` (fábrica de `UnidadTrabajoCotizaciones`), `reloj` e `identificadores`. Al llamarlo con un `ProcesarPeticionCotizacion` devuelve `ResultadoProcesamiento` (definido en el mismo archivo), con `id_cotizacion` opcional y el indicador `nueva`. La llamada va decorada con `reintentar_colision`.

```text
procesar(comando):
  abrir unidad                                         // sesión y transacción nuevas
    existente ← unidad.cotizaciones.obtener_por_peticion(comando.datos.id_peticion)
    si existe:
      si existente.peticion ≠ comando.datos → lanzar ConflictoPeticion   // revierte todo
      si unidad.registrar_recepcion(consumidor, comando) → unidad.confirmar()
      devolver (existente.id, nueva = falso)           // sin nueva cotización ni nuevo evento
    si no unidad.registrar_recepcion(consumidor, comando):
      devolver (ninguna, nueva = falso)                // defensivo: mismo comando ya confirmado
    catalogo ← unidad.catalogos.obtener_vigente()      // se lee DESPUÉS de descartar duplicados
    cotizacion ← Cotizacion.resolver(id = nuevo ID, peticion = comando.datos, origen = comando.origen,
                                     catalogo, id_evento = nuevo ID, instante = reloj.ahora())
                                                       // CatalogoNoDisponible revierte también el inbox
    unidad.cotizaciones.guardar(cotizacion)
    por cada evento retirado de cotizacion: unidad.registrar_salida(evento)
    unidad.confirmar()
    devolver (cotizacion.id, nueva = verdadero)
```

Reglas: el handler no publica mensajes, no hace ACK y no conoce Pulsar. Una segunda petición con otro `command_id` y los mismos datos solo añade su marca de inbox. La salida original sigue en el outbox y no se crea otra.

**`config/bootstrap.py` (inicio):** función `componer_procesamiento(crear_unidad, reloj, identificadores)`, que construye el handler. Sin clases fábrica. La variante SQL se añade en el Paso 29.

## Paso 21 — Dobles en memoria, pruebas y evidencia

**Archivos:** `tests/unitarias/aplicacion/__init__.py`, `tests/unitarias/aplicacion/datos.py` (fábricas de `DatosPeticion`, `OrigenComando` y el catálogo de 00 §9), `tests/unitarias/aplicacion/dobles/{__init__,reloj,identificadores,repositorios,unidad_trabajo}.py`, `tests/unitarias/aplicacion/test_procesar_peticion.py`, `docs/evidencias/03-aplicacion.md`.

**Dobles:**
- Reloj fijo e identificadores secuenciales deterministas.
- Repositorios en memoria.
- UoW en memoria **transaccional**: las escrituras se acumulan y solo se aplican al confirmar; revertir o salir por excepción las descarta. Expone lo confirmado (cotizaciones, marcas de inbox, salidas) e incluye un gancho configurable para fallar en `registrar_salida` o en `guardar`, y otro para lanzar `ColisionPersistencia` en el primer intento.

**Pruebas (escribirlas primero):**
1. F1–F5: una cotización, una marca de inbox y una salida del tipo correcto.
2. Catálogo ausente: se propaga `CatalogoNoDisponible` y no queda cotización, inbox ni salida.
3. Fallo al registrar la salida: no queda cotización ni marca de inbox.
4. Rechazo válido: sí confirma inbox y salida.
5. El mismo comando dos veces: la segunda devuelve `nueva = falso` y no hay salida adicional.
6. Otro `command_id` con los mismos datos: hay dos marcas de inbox, una sola salida y el mismo `id_cotizacion`.
7. Se cambia el catálogo activo entre la primera y la segunda entrega: se devuelve la resolución original.
8. Misma `id_peticion` con otra categoría o red: `ConflictoPeticion` y nada escrito.
9. `ColisionPersistencia` en el primer intento: el reintento encuentra la cotización existente y no crea otra.

**Verificación:** verificación estándar verde. La evidencia 03 declara que no hay durabilidad ni consumo autónomo, y que eso llega con las fases 04 y 05.
