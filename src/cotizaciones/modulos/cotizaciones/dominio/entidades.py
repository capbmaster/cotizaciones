from dataclasses import dataclass
from datetime import datetime
from typing import Self
from uuid import UUID

from cotizaciones.modulos.cotizaciones.dominio.eventos import (
    CotizacionRechazada,
    CotizacionRegistrada,
)
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    DatosPeticion,
    EstadoCotizacion,
    OrigenComando,
    ResultadoCotizacion,
    TipoRed,
)
from cotizaciones.modulos.cotizaciones.dominio.servicios import exigir_catalogo, resolver_oferta
from cotizaciones.seedwork.dominio.entidades import AgregacionRaiz
from cotizaciones.seedwork.dominio.validaciones import validar_instante, validar_version

# Una ronda por petición en esta POC (D04).
VERSION_COTIZACION = 1


@dataclass(frozen=True, eq=False, kw_only=True)
class Cotizacion(AgregacionRaiz):
    peticion: DatosPeticion
    origen: OrigenComando
    version_catalogo: int
    version_cotizacion: int
    resultado: ResultadoCotizacion
    resuelta_en: datetime

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            not isinstance(self.peticion, DatosPeticion)
            or not isinstance(self.origen, OrigenComando)
            or not isinstance(self.resultado, ResultadoCotizacion)
        ):
            raise ValueError("Peticion, origen o resultado de cotizacion invalidos")
        validar_version(self.version_catalogo)
        validar_version(self.version_cotizacion)
        if self.version_cotizacion != VERSION_COTIZACION:
            raise ValueError("La version de cotizacion debe ser 1: una ronda por peticion")
        validar_instante(self.resuelta_en)
        if self.origen.correlacion != self.peticion.id_solicitud:
            raise ValueError("La correlacion debe ser igual a la solicitud de la peticion")
        oferta = self.resultado.oferta
        if oferta is not None:
            if oferta.tipo_red is not self.peticion.tipo_red:
                raise ValueError("La oferta propuesta pertenece a otra red")
            if oferta.categoria != self.peticion.clave_categoria:
                raise ValueError("La oferta propuesta pertenece a otra categoria")
            if (
                oferta.tipo_red is TipoRed.HOMOLOGADA_PARTNER
                and oferta.id_partner != self.peticion.id_partner
            ):
                raise ValueError("La oferta homologada pertenece a otro partner")

    @property
    def estado(self) -> EstadoCotizacion:
        return self.resultado.estado

    @classmethod
    def resolver(
        cls,
        *,
        id: UUID,
        peticion: DatosPeticion,
        origen: OrigenComando,
        catalogo: CatalogoVigente | None,
        id_evento: UUID,
        instante: datetime,
    ) -> Self:
        vigente = exigir_catalogo(catalogo)
        resultado = resolver_oferta(peticion, vigente)
        cotizacion = cls(
            id=id,
            peticion=peticion,
            origen=origen,
            version_catalogo=vigente.version,
            version_cotizacion=VERSION_COTIZACION,
            resultado=resultado,
            resuelta_en=instante,
        )
        if resultado.oferta is not None:
            cotizacion._registrar_evento(
                CotizacionRegistrada(
                    id_evento=id_evento,
                    instante=instante,
                    id_cotizacion=id,
                    peticion=peticion,
                    id_comando=origen.id_comando,
                    correlacion=origen.correlacion,
                    version_catalogo=vigente.version,
                    version_cotizacion=VERSION_COTIZACION,
                    id_proveedor=resultado.oferta.id_proveedor,
                    precio=resultado.oferta.precio,
                )
            )
        elif resultado.motivo is not None:
            cotizacion._registrar_evento(
                CotizacionRechazada(
                    id_evento=id_evento,
                    instante=instante,
                    id_cotizacion=id,
                    peticion=peticion,
                    id_comando=origen.id_comando,
                    correlacion=origen.correlacion,
                    version_catalogo=vigente.version,
                    version_cotizacion=VERSION_COTIZACION,
                    motivo=resultado.motivo,
                )
            )
        return cotizacion
