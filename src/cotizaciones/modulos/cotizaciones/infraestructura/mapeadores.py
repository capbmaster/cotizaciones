from collections.abc import Sequence
from typing import Any

from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoInvalido
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    Dinero,
    EstadoCotizacion,
    MotivoRechazo,
    OfertaCatalogo,
    OrigenComando,
    ResultadoCotizacion,
    TipoRed,
)
from cotizaciones.modulos.cotizaciones.infraestructura.orm import (
    CatalogoSQL,
    CotizacionSQL,
    OfertaCatalogoSQL,
)
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import (
    decodificar_peticion,
    serializar_peticion,
)


def valores_cotizacion(cotizacion: Cotizacion) -> dict[str, Any]:
    peticion = cotizacion.peticion
    origen = cotizacion.origen
    oferta = cotizacion.resultado.oferta
    motivo = cotizacion.resultado.motivo
    return dict(
        id=cotizacion.id,
        id_peticion=peticion.id_peticion,
        id_trabajo=peticion.id_trabajo,
        id_solicitud=peticion.id_solicitud,
        id_partner=peticion.id_partner,
        peticion=serializar_peticion(peticion),
        id_comando_origen=origen.id_comando,
        correlacion=origen.correlacion,
        causacion=origen.causacion,
        instante_comando=origen.instante,
        version_catalogo=cotizacion.version_catalogo,
        version_cotizacion=cotizacion.version_cotizacion,
        estado=cotizacion.estado.value,
        id_proveedor=oferta.id_proveedor if oferta is not None else None,
        importe_menor=oferta.precio.importe_menor if oferta is not None else None,
        moneda=oferta.precio.moneda if oferta is not None else None,
        motivo=motivo.value if motivo is not None else None,
        duracion_estimada_minutos=oferta.duracion_estimada_minutos if oferta is not None else None,
        resuelta_en=cotizacion.resuelta_en,
    )


def cargar_cotizacion(fila: CotizacionSQL) -> Cotizacion:
    """Reconstruye el agregado con su constructor: no registra eventos."""
    peticion = decodificar_peticion(fila.peticion)
    if fila.estado == EstadoCotizacion.PROPUESTA.value:
        if fila.id_proveedor is None or fila.importe_menor is None or fila.moneda is None:
            raise ValueError("Fila de propuesta incompleta")
        resultado = ResultadoCotizacion(
            estado=EstadoCotizacion.PROPUESTA,
            oferta=OfertaCatalogo(
                id_proveedor=fila.id_proveedor,
                categoria=peticion.clave_categoria,
                tipo_red=peticion.tipo_red,
                id_partner=(
                    peticion.id_partner if peticion.tipo_red is TipoRed.HOMOLOGADA_PARTNER else None
                ),
                precio=Dinero(importe_menor=fila.importe_menor, moneda=fila.moneda),
                duracion_estimada_minutos=fila.duracion_estimada_minutos,
            ),
        )
    else:
        resultado = ResultadoCotizacion(
            estado=EstadoCotizacion(fila.estado),
            motivo=MotivoRechazo(fila.motivo) if fila.motivo is not None else None,
        )
    return Cotizacion(
        id=fila.id,
        peticion=peticion,
        origen=OrigenComando(
            id_comando=fila.id_comando_origen,
            instante=fila.instante_comando,
            correlacion=fila.correlacion,
            causacion=fila.causacion,
        ),
        version_catalogo=fila.version_catalogo,
        version_cotizacion=fila.version_cotizacion,
        resultado=resultado,
        resuelta_en=fila.resuelta_en,
    )


def valores_oferta(version: int, oferta: OfertaCatalogo) -> dict[str, Any]:
    return dict(
        version_catalogo=version,
        id_proveedor=oferta.id_proveedor,
        categoria=oferta.categoria,
        tipo_red=oferta.tipo_red.value,
        id_partner=oferta.id_partner,
        importe_menor=oferta.precio.importe_menor,
        moneda=oferta.precio.moneda,
        duracion_estimada_minutos=oferta.duracion_estimada_minutos,
    )


def cargar_catalogo(fila: CatalogoSQL, ofertas: Sequence[OfertaCatalogoSQL]) -> CatalogoVigente:
    """Construye el catálogo con el dominio; datos que violan invariantes → CatalogoInvalido."""
    try:
        return CatalogoVigente(
            version=fila.version,
            ofertas=tuple(
                OfertaCatalogo(
                    id_proveedor=oferta.id_proveedor,
                    categoria=oferta.categoria,
                    tipo_red=TipoRed(oferta.tipo_red),
                    id_partner=oferta.id_partner,
                    precio=Dinero(importe_menor=oferta.importe_menor, moneda=oferta.moneda),
                    duracion_estimada_minutos=oferta.duracion_estimada_minutos,
                )
                for oferta in ofertas
            ),
        )
    except ValueError as error:
        raise CatalogoInvalido(str(error)) from error
