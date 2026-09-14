from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoNoDisponible
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    DatosPeticion,
    EstadoCotizacion,
    MotivoRechazo,
    ResultadoCotizacion,
    TipoRed,
)


def exigir_catalogo(catalogo: CatalogoVigente | None) -> CatalogoVigente:
    if catalogo is None:
        raise CatalogoNoDisponible("No hay una version activa del catalogo")
    return catalogo


def resolver_oferta(
    peticion: DatosPeticion, catalogo: CatalogoVigente | None
) -> ResultadoCotizacion:
    """Regla de selección de la POC (00 §8): orden estable por proveedor, no el mejor precio."""
    vigente = exigir_catalogo(catalogo)
    de_categoria = vigente.ofertas_de_categoria(peticion.clave_categoria)
    if not de_categoria:
        return ResultadoCotizacion(
            estado=EstadoCotizacion.RECHAZADA, motivo=MotivoRechazo.SIN_OFERTA_PARA_CATEGORIA
        )
    if peticion.tipo_red is TipoRed.GENERAL_HDA:
        candidatas = [o for o in de_categoria if o.tipo_red is TipoRed.GENERAL_HDA]
    else:
        candidatas = [
            o
            for o in de_categoria
            if o.tipo_red is TipoRed.HOMOLOGADA_PARTNER and o.id_partner == peticion.id_partner
        ]
    if not candidatas:
        return ResultadoCotizacion(
            estado=EstadoCotizacion.RECHAZADA, motivo=MotivoRechazo.SIN_PROVEEDOR_EN_RED
        )
    elegida = min(candidatas, key=lambda oferta: str(oferta.id_proveedor))
    return ResultadoCotizacion(estado=EstadoCotizacion.PROPUESTA, oferta=elegida)
