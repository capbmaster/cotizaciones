import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.dominio.eventos import (
    CotizacionRechazada,
    CotizacionRegistrada,
)
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoInvalido
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    DatosPeticion,
    Dinero,
    MotivoRechazo,
    OfertaCatalogo,
    OrigenComando,
    TipoRed,
    TipoSolicitud,
    normalizar_categoria,
)
from cotizaciones.seedwork.dominio.eventos import EventoDominio
from cotizaciones.seedwork.infraestructura.serializacion import (
    Documento,
    entero,
    identidad,
    instante,
    objeto,
    texto,
)

VERSION_FORMATO = 1


def _utc(valor: datetime) -> str:
    return valor.astimezone(UTC).isoformat()


def serializar_peticion(datos: DatosPeticion) -> Documento:
    return dict(
        id_peticion=str(datos.id_peticion),
        id_trabajo=str(datos.id_trabajo),
        id_solicitud=str(datos.id_solicitud),
        id_partner=str(datos.id_partner),
        categoria=datos.categoria,
        tipo_solicitud=datos.tipo_solicitud.value,
        tipo_red=datos.tipo_red.value,
        id_politica=str(datos.id_politica),
        version_politica=datos.version_politica,
    )


def decodificar_peticion(documento: Documento) -> DatosPeticion:
    return DatosPeticion(
        id_peticion=identidad(documento, "id_peticion"),
        id_trabajo=identidad(documento, "id_trabajo"),
        id_solicitud=identidad(documento, "id_solicitud"),
        id_partner=identidad(documento, "id_partner"),
        categoria=texto(documento, "categoria"),
        tipo_solicitud=TipoSolicitud(texto(documento, "tipo_solicitud")),
        tipo_red=TipoRed(texto(documento, "tipo_red")),
        id_politica=identidad(documento, "id_politica"),
        version_politica=entero(documento, "version_politica"),
    )


def serializar_comando(comando: ProcesarPeticionCotizacion) -> Documento:
    """Documento del inbox: dos comandos iguales producen documentos idénticos."""
    origen = comando.origen
    return dict(
        command_id=str(origen.id_comando),
        instante=_utc(origen.instante),
        correlacion=str(origen.correlacion),
        causacion=str(origen.causacion),
        datos=serializar_peticion(comando.datos),
    )


def decodificar_comando(documento: Documento) -> ProcesarPeticionCotizacion:
    try:
        return ProcesarPeticionCotizacion(
            origen=OrigenComando(
                id_comando=identidad(documento, "command_id"),
                instante=instante(documento, "instante"),
                correlacion=identidad(documento, "correlacion"),
                causacion=identidad(documento, "causacion"),
            ),
            datos=decodificar_peticion(objeto(documento, "datos")),
        )
    except (KeyError, TypeError) as error:
        raise ValueError("Documento de comando invalido") from error


def serializar_evento(evento: EventoDominio) -> Documento:
    resultado: Documento
    if isinstance(evento, CotizacionRegistrada):
        resultado = dict(
            id_proveedor=str(evento.id_proveedor),
            importe_menor=evento.precio.importe_menor,
            moneda=evento.precio.moneda,
        )
    elif isinstance(evento, CotizacionRechazada):
        resultado = dict(motivo=evento.motivo.value)
    else:
        raise ValueError(f"Evento sin serializacion: {type(evento).__name__}")
    documento: Documento = dict(
        tipo=type(evento).__name__,
        version_formato=VERSION_FORMATO,
        id_evento=str(evento.id_evento),
        instante=_utc(evento.instante),
        id_cotizacion=str(evento.id_cotizacion),
        peticion=serializar_peticion(evento.peticion),
        id_comando=str(evento.id_comando),
        correlacion=str(evento.correlacion),
        version_catalogo=evento.version_catalogo,
        version_cotizacion=evento.version_cotizacion,
        **resultado,
    )
    decodificar_evento(documento)
    return documento


def decodificar_evento(documento: Documento) -> CotizacionRegistrada | CotizacionRechazada:
    try:
        if entero(documento, "version_formato") != VERSION_FORMATO:
            raise ValueError("Formato de evento desconocido")
        tipo = texto(documento, "tipo")
        comunes: dict[str, Any] = dict(
            id_evento=identidad(documento, "id_evento"),
            instante=instante(documento, "instante"),
            id_cotizacion=identidad(documento, "id_cotizacion"),
            peticion=decodificar_peticion(objeto(documento, "peticion")),
            id_comando=identidad(documento, "id_comando"),
            correlacion=identidad(documento, "correlacion"),
            version_catalogo=entero(documento, "version_catalogo"),
            version_cotizacion=entero(documento, "version_cotizacion"),
        )
        if tipo == "CotizacionRegistrada":
            return CotizacionRegistrada(
                **comunes,
                id_proveedor=identidad(documento, "id_proveedor"),
                precio=Dinero(
                    importe_menor=entero(documento, "importe_menor"),
                    moneda=texto(documento, "moneda"),
                ),
            )
        if tipo == "CotizacionRechazada":
            return CotizacionRechazada(**comunes, motivo=MotivoRechazo(texto(documento, "motivo")))
        raise ValueError(f"Tipo de evento desconocido: {tipo}")
    except (KeyError, TypeError) as error:
        raise ValueError("Documento de evento invalido") from error


def _oferta_desde_documento(documento: Documento) -> OfertaCatalogo:
    return OfertaCatalogo(
        id_proveedor=identidad(documento, "id_proveedor"),
        categoria=normalizar_categoria(texto(documento, "categoria")),
        tipo_red=TipoRed(texto(documento, "tipo_red")),
        id_partner=None if documento["id_partner"] is None else identidad(documento, "id_partner"),
        precio=Dinero(
            importe_menor=entero(documento, "importe_menor"), moneda=texto(documento, "moneda")
        ),
    )


def catalogo_desde_documento(documento: Documento) -> CatalogoVigente:
    """Lee un archivo `datos/catalogos/catalogo-vN.json` y lo valida con el dominio."""
    try:
        ofertas = documento["ofertas"]
        if not isinstance(ofertas, list):
            raise ValueError("ofertas debe ser una lista")
        return CatalogoVigente(
            version=documento["version"],
            ofertas=tuple(_oferta_desde_documento(oferta) for oferta in ofertas),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise CatalogoInvalido(f"Documento de catalogo invalido: {error!r}") from error


def huella_catalogo(catalogo: CatalogoVigente) -> str:
    """SHA-256 de un JSON canónico: claves y ofertas ordenadas, categorías ya normalizadas."""
    ordenadas = sorted(
        catalogo.ofertas,
        key=lambda o: (
            o.categoria,
            o.tipo_red.value,
            str(o.id_partner or ""),
            str(o.id_proveedor),
        ),
    )
    canonico = dict(
        version=catalogo.version,
        ofertas=[
            dict(
                id_proveedor=str(o.id_proveedor),
                categoria=o.categoria,
                tipo_red=o.tipo_red.value,
                id_partner=str(o.id_partner) if o.id_partner is not None else None,
                importe_menor=o.precio.importe_menor,
                moneda=o.precio.moneda,
            )
            for o in ordenadas
        ],
    )
    texto_canonico = json.dumps(canonico, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(texto_canonico.encode("utf-8")).hexdigest()
