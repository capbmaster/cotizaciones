# Fase 02 — Modelo de dominio (Pasos 10–16)

Corresponde a `planes-otros-microservicios/cotizaciones/02-modelo-cotizacion-catalogo.md`. Resultado: el agregado `Cotizacion`, el catálogo y la regla de selección de [00 §8](00-contratos-y-datos.md), como código puro sin SQLAlchemy, Pulsar ni FastAPI. Ruta base: `src/cotizaciones/modulos/cotizaciones/dominio/`. Crear los `__init__.py` vacíos de `modulos/`, `modulos/cotizaciones/` y `dominio/`.

Todas las pruebas de esta fase van en `tests/unitarias/dominio/` (con `__init__.py`) y se escriben **antes** de la implementación.

---

## Paso 10 — Seedwork de dominio

**Archivos:** `src/cotizaciones/seedwork/dominio/{__init__,entidades,eventos,objetos_valor,validaciones}.py`, `tests/unitarias/dominio/test_seedwork.py`.

**Acción:** copiar de Entrada `seedwork/dominio/entidades.py` (`Entidad`, `AgregacionRaiz` con eventos pendientes y `retirar_eventos`), `eventos.py` (`EventoDominio` con `id_evento` e `instante`), `objetos_valor.py` (`ObjetoValor`) y `validaciones.py` (`validar_identidad`, `validar_instante`, `validar_version`, `validar_texto`). Solo cambian los imports. No copiar `repositorios.py` de seedwork: los puertos viven en el módulo.

**Pruebas:** igualdad de entidades por tipo e ID; `retirar_eventos` vacía la lista; UUID nulo, instante sin zona, versión 0 o booleana y texto en blanco fallan.

## Paso 11 — Objetos valor de la petición y del dinero

**Archivo:** `dominio/objetos_valor.py`. **Pruebas:** `tests/unitarias/dominio/test_objetos_valor.py`.

**Contenido:**
- Enumeraciones de texto: `TipoRed` (`GENERAL_HDA`, `HOMOLOGADA_PARTNER`), `TipoSolicitud` (`SINIESTRO`, `INSTALACION`), `EstadoCotizacion` (`PROPUESTA`, `RECHAZADA`), `MotivoRechazo` (`SIN_OFERTA_PARA_CATEGORIA`, `SIN_PROVEEDOR_EN_RED`). Son tipos propios de Cotizaciones; no se importan de Entrada.
- Función `normalizar_categoria(texto)`: quita espacios al inicio y al final y aplica `casefold`; si el resultado queda vacío lanza `ValueError`.
- `Dinero`: `importe_menor` (entero estricto, no booleano, > 0) y `moneda` (exactamente tres letras mayúsculas).
- `DatosPeticion`: `id_peticion`, `id_trabajo`, `id_solicitud`, `id_partner`, `categoria` (texto tal como llegó), `tipo_solicitud`, `tipo_red`, `id_politica`, `version_politica`. Valida UUID no nulos, texto visible, enumeraciones y versión ≥ 1. Propiedad `clave_categoria` = `normalizar_categoria(categoria)`. Es la **copia canónica** de la petición: dos peticiones son la misma si sus `DatosPeticion` son iguales campo a campo.
- `OrigenComando`: `id_comando`, `instante`, `correlacion`, `causacion`. Valida UUID e instante con zona, y que `correlacion` sea igual al `id_solicitud` de la petición (esa comprobación la hace el agregado, que conoce ambos).

**Pruebas:** importe 0, negativo, booleano o decimal falla; moneda `cop` o `COPX` falla; `normalizar_categoria("  Plomeria ")` da `plomeria`; categoría de solo espacios falla; `DatosPeticion` con enumeración inválida falla; dos `DatosPeticion` iguales son iguales y difieren si cambia cualquier campo.

## Paso 12 — Catálogo vigente y ofertas

**Archivos:** `dominio/objetos_valor.py` (continuación), `dominio/excepciones.py`. **Pruebas:** `tests/unitarias/dominio/test_catalogo.py`.

**Contenido:**
- `excepciones.py`: `ErrorCatalogo` (error técnico base), con subclases `CatalogoNoDisponible` (no hay versión activa) y `CatalogoInvalido` (datos del catálogo que violan invariantes al reconstruirlo). Ninguna produce un rechazo empresarial.
- `OfertaCatalogo`: `id_proveedor`, `categoria` (ya normalizada), `tipo_red`, `id_partner` (opcional) y `precio` (`Dinero`). Invariantes: la categoría debe ser igual a su forma normalizada; la red general exige partner ausente; la red homologada exige partner presente. Si una invariante falla se lanza `CatalogoInvalido`.
- `CatalogoVigente`: `version` (≥ 1) y `ofertas` (tupla no vacía). No admite dos ofertas con la misma combinación (categoría, red, partner, proveedor). Método `ofertas_de_categoria(clave)`.

**Pruebas:** oferta general con partner falla; oferta homologada sin partner falla; categoría sin normalizar falla; catálogo sin ofertas o con duplicados falla; `ofertas_de_categoria` filtra por clave exacta.

## Paso 13 — Resultado y servicio de selección

**Archivos:** `dominio/objetos_valor.py` (`ResultadoCotizacion`), `dominio/servicios.py`. **Pruebas:** `tests/unitarias/dominio/test_seleccion.py`.

**Contenido:**
- `ResultadoCotizacion`: `estado`, `oferta` (opcional) y `motivo` (opcional). Si es PROPUESTA exige oferta y ningún motivo; si es RECHAZADA exige motivo y ninguna oferta. No se puede construir un estado mixto.
- `servicios.resolver_oferta(peticion, catalogo)`: función pura que implementa exactamente los pasos 1–7 de [00 §8](00-contratos-y-datos.md). Recibe el catálogo ya cargado (o ausente) y nunca accede a SQL.

**Pruebas (tabla de decisiones con el catálogo de 00 §9 construido en memoria):** F1–F6; empate `a101`/`a102` elige `a101` aunque sea más caro; homologada sin candidato no recurre a la red general; catálogo ausente lanza `CatalogoNoDisponible`; la oferta elegida para una red homologada pertenece al partner de la petición.

## Paso 14 — Eventos de dominio

**Archivo:** `dominio/eventos.py`. **Pruebas:** `tests/unitarias/dominio/test_eventos.py`.

**Contenido (hechos internos inmutables; no son esquemas Avro):**
- `CotizacionRegistrada` (hereda `EventoDominio`): `id_cotizacion`, `peticion` (`DatosPeticion`), `id_comando`, `correlacion`, `version_catalogo`, `version_cotizacion`, `id_proveedor` y `precio` (`Dinero`).
- `CotizacionRechazada`: los mismos campos hasta `version_cotizacion`, más `motivo`.
- Ambos validan identidades, versiones y tipos en `__post_init__`.

**Pruebas:** construcción válida; campos nulos o versiones inválidas fallan; los eventos son inmutables.

## Paso 15 — Agregado `Cotizacion`

**Archivo:** `dominio/entidades.py`. **Pruebas:** `tests/unitarias/dominio/test_cotizacion.py`.

**Contenido:** `Cotizacion` hereda `AgregacionRaiz`, con `id`, `peticion`, `origen`, `version_catalogo`, `version_cotizacion`, `resultado` y `resuelta_en`.

Invariantes de `__post_init__`:
- `version_catalogo` ≥ 1; `version_cotizacion` = 1 (una ronda por petición, D04); `resuelta_en` con zona horaria.
- `origen.correlacion` = `peticion.id_solicitud`.
- Si hay propuesta: la oferta tiene la misma red y la misma clave de categoría que la petición y, si la red es homologada, el mismo partner. Así se garantiza que nunca se persiste una oferta de otro partner.

Fábrica `Cotizacion.resolver(...)` con `id`, `peticion`, `origen`, `catalogo`, `id_evento` e `instante` (IDs e instante inyectados; nunca generados dentro del dominio):

```text
resultado ← resolver_oferta(peticion, catalogo)          // puede lanzar CatalogoNoDisponible
cotizacion ← nueva Cotizacion(id, peticion, origen, catalogo.version, 1, resultado, instante)
si resultado es PROPUESTA: registrar evento CotizacionRegistrada(id_evento, instante, datos de la oferta)
si no:                     registrar evento CotizacionRechazada(id_evento, instante, motivo)
devolver cotizacion                                       // exactamente un evento pendiente
```

Reconstruir con el constructor (lo hará el mapeador SQL) **no registra eventos**.

**Pruebas:** `resolver` produce el estado y el único evento correctos para F1–F5; `retirar_eventos` deja el agregado sin pendientes; reconstruir no produce eventos; una propuesta de otro partner o de otra red falla; una correlación distinta de la solicitud falla; `version_cotizacion` ≠ 1 falla.

## Paso 16 — Puertos de repositorio, aislamiento y evidencia

**Archivos:** `dominio/repositorios.py`, ampliación de `tests/unitarias/test_aislamiento.py`, `docs/evidencias/02-dominio.md`.

**Contenido de `repositorios.py` (protocolos mínimos, sin CRUD genérico):**
- `RepositorioCotizaciones`: `obtener_por_peticion(id_peticion)` devuelve la cotización o nada; `guardar(cotizacion)` la agrega.
- `RepositorioCatalogo`: `obtener_vigente()` devuelve `CatalogoVigente` o nada.

**Aislamiento:** añadir a la prueba los módulos de dominio y afirmar que no cargan `sqlalchemy`, `pulsar`, `fastapi` ni `solicitudes_partner`.

**Verificación:** verificación estándar verde; la evidencia 02 incluye la tabla F1–F7 con la prueba que cubre cada fila y declara que el catálogo sintético y la selección por orden de proveedor son decisiones de la POC.
