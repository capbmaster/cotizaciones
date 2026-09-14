from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.dominio.eventos import (
    CotizacionRechazada,
    CotizacionRegistrada,
)
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    DatosPeticion,
    OrigenComando,
    TipoRed,
    TipoSolicitud,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.eventos import (
    CotizacionRechazadaV1,
    CotizacionRegistradaV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import decodificar_evento
from cotizaciones.seedwork.infraestructura.serializacion import Documento

TIPO_COMANDO = "SolicitarCotizacion.v1"
TIPO_REGISTRADA = "CotizacionRegistrada.v1"
TIPO_RECHAZADA = "CotizacionRechazada.v1"
VERSION_CONTRATO_RESULTADOS = 1


class ComandoInvalido(ValueError):
    """El mensaje viola una regla de 00 §3: se pausa el consumo, nunca es un rechazo."""


def _texto(mensaje: Any, campo: str) -> str:
    valor = getattr(mensaje, campo, None)
    if not isinstance(valor, str) or not valor.strip():
        raise ComandoInvalido(f"{campo}: texto ausente o sin caracteres visibles")
    return valor


def _uuid(mensaje: Any, campo: str) -> UUID:
    texto = _texto(mensaje, campo)
    try:
        valor = UUID(texto)
    except ValueError:
        raise ComandoInvalido(f"{campo}: {texto!r} no es un UUID") from None
    if valor.int == 0:
        raise ComandoInvalido(f"{campo}: UUID nulo")
    return valor


def _entero(mensaje: Any, campo: str, minimo: int) -> int:
    valor = getattr(mensaje, campo, None)
    if type(valor) is not int or valor < minimo:
        raise ComandoInvalido(f"{campo}: debe ser un entero mayor o igual que {minimo}")
    return valor


def _instante(mensaje: Any, campo: str) -> datetime:
    texto = _texto(mensaje, campo)
    try:
        valor = datetime.fromisoformat(texto)
    except ValueError:
        raise ComandoInvalido(f"{campo}: {texto!r} no es ISO 8601") from None
    if valor.utcoffset() is None:
        raise ComandoInvalido(f"{campo}: falta la zona horaria")
    return valor


def _valor[E: StrEnum](mensaje: Any, campo: str, enumeracion: type[E]) -> E:
    texto = _texto(mensaje, campo)
    try:
        return enumeracion(texto)
    except ValueError:
        raise ComandoInvalido(f"{campo}: valor no admitido {texto!r}") from None


def comando_desde_mensaje(mensaje: Any) -> ProcesarPeticionCotizacion:
    """Traduce SolicitarCotizacionV1 al comando propio aplicando todas las reglas de 00 §3."""
    tipo = _texto(mensaje, "tipo")
    if tipo != TIPO_COMANDO:
        raise ComandoInvalido(f"tipo: se esperaba {TIPO_COMANDO!r} y llego {tipo!r}")
    _entero(mensaje, "version_contrato", 1)
    id_solicitud = _uuid(mensaje, "id_solicitud")
    correlacion = _uuid(mensaje, "correlacion")
    if correlacion != id_solicitud:
        raise ComandoInvalido("correlacion: debe ser igual a id_solicitud")
    id_comando = _uuid(mensaje, "command_id")
    instante = _instante(mensaje, "instante")
    causacion = _uuid(mensaje, "causacion")
    id_peticion = _uuid(mensaje, "id_peticion")
    id_trabajo = _uuid(mensaje, "id_trabajo")
    id_partner = _uuid(mensaje, "id_partner")
    categoria = _texto(mensaje, "categoria")
    tipo_solicitud = _valor(mensaje, "tipo_solicitud", TipoSolicitud)
    tipo_red = _valor(mensaje, "tipo_red", TipoRed)
    id_politica = _uuid(mensaje, "id_politica")
    version_politica = _entero(mensaje, "version_politica", 1)
    try:
        return ProcesarPeticionCotizacion(
            origen=OrigenComando(
                id_comando=id_comando,
                instante=instante,
                correlacion=correlacion,
                causacion=causacion,
            ),
            datos=DatosPeticion(
                id_peticion=id_peticion,
                id_trabajo=id_trabajo,
                id_solicitud=id_solicitud,
                id_partner=id_partner,
                categoria=categoria,
                tipo_solicitud=tipo_solicitud,
                tipo_red=tipo_red,
                id_politica=id_politica,
                version_politica=version_politica,
            ),
        )
    except ValueError as error:
        raise ComandoInvalido(str(error)) from error


def _comunes(evento: CotizacionRegistrada | CotizacionRechazada, tipo: str) -> dict[str, Any]:
    peticion = evento.peticion
    return dict(
        event_id=str(evento.id_evento),
        tipo=tipo,
        version_contrato=VERSION_CONTRATO_RESULTADOS,
        instante=evento.instante.astimezone(UTC).isoformat(),
        correlacion=str(evento.correlacion),
        causacion=str(evento.id_comando),
        id_peticion=str(peticion.id_peticion),
        id_trabajo=str(peticion.id_trabajo),
        id_solicitud=str(peticion.id_solicitud),
        id_partner=str(peticion.id_partner),
        version_catalogo=evento.version_catalogo,
        version_cotizacion=evento.version_cotizacion,
    )


def mensaje_registrada(documento: Documento) -> Any:
    """Construye el Record v1 desde el documento guardado en el outbox; nunca lee el catálogo."""
    evento = decodificar_evento(documento)
    if not isinstance(evento, CotizacionRegistrada):
        raise ValueError(f"Se esperaba CotizacionRegistrada y llego {type(evento).__name__}")
    return CotizacionRegistradaV1(
        **_comunes(evento, TIPO_REGISTRADA),
        id_cotizacion=str(evento.id_cotizacion),
        id_proveedor=str(evento.id_proveedor),
        importe_menor=evento.precio.importe_menor,
        moneda=evento.precio.moneda,
        categoria=evento.peticion.categoria,
        tipo_red=evento.peticion.tipo_red.value,
    )


def mensaje_rechazada(documento: Documento) -> Any:
    evento = decodificar_evento(documento)
    if not isinstance(evento, CotizacionRechazada):
        raise ValueError(f"Se esperaba CotizacionRechazada y llego {type(evento).__name__}")
    return CotizacionRechazadaV1(**_comunes(evento, TIPO_RECHAZADA), motivo=evento.motivo.value)
