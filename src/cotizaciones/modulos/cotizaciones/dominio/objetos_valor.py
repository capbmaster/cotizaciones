import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoInvalido
from cotizaciones.seedwork.dominio.objetos_valor import ObjetoValor
from cotizaciones.seedwork.dominio.validaciones import (
    validar_identidad,
    validar_instante,
    validar_texto,
    validar_version,
)

_MONEDA = re.compile(r"[A-Z]{3}")


class TipoRed(StrEnum):
    GENERAL_HDA = "GENERAL_HDA"
    HOMOLOGADA_PARTNER = "HOMOLOGADA_PARTNER"


class TipoSolicitud(StrEnum):
    SINIESTRO = "SINIESTRO"
    INSTALACION = "INSTALACION"


class EstadoCotizacion(StrEnum):
    PROPUESTA = "PROPUESTA"
    RECHAZADA = "RECHAZADA"


class MotivoRechazo(StrEnum):
    SIN_OFERTA_PARA_CATEGORIA = "SIN_OFERTA_PARA_CATEGORIA"
    SIN_PROVEEDOR_EN_RED = "SIN_PROVEEDOR_EN_RED"


def normalizar_categoria(texto: str) -> str:
    clave = texto.strip().casefold() if isinstance(texto, str) else ""
    if not clave:
        raise ValueError("La categoria debe contener al menos un caracter visible")
    return clave


@dataclass(frozen=True, kw_only=True)
class Dinero(ObjetoValor):
    importe_menor: int
    moneda: str

    def __post_init__(self) -> None:
        if type(self.importe_menor) is not int or self.importe_menor <= 0:
            raise ValueError("El importe debe ser un entero positivo en unidades menores")
        if not isinstance(self.moneda, str) or not _MONEDA.fullmatch(self.moneda):
            raise ValueError("La moneda debe ser un codigo de tres letras mayusculas")


@dataclass(frozen=True, kw_only=True)
class DatosPeticion(ObjetoValor):
    """Copia canónica de la petición: dos peticiones son la misma si son iguales campo a campo."""

    id_peticion: UUID
    id_trabajo: UUID
    id_solicitud: UUID
    id_partner: UUID
    categoria: str
    tipo_solicitud: TipoSolicitud
    tipo_red: TipoRed
    id_politica: UUID
    version_politica: int

    def __post_init__(self) -> None:
        for identidad in (
            self.id_peticion,
            self.id_trabajo,
            self.id_solicitud,
            self.id_partner,
            self.id_politica,
        ):
            validar_identidad(identidad)
        validar_texto(self.categoria)
        if not isinstance(self.tipo_solicitud, TipoSolicitud):
            raise ValueError("Tipo de solicitud invalido")
        if not isinstance(self.tipo_red, TipoRed):
            raise ValueError("Tipo de red invalido")
        validar_version(self.version_politica)

    @property
    def clave_categoria(self) -> str:
        return normalizar_categoria(self.categoria)


@dataclass(frozen=True, kw_only=True)
class OrigenComando(ObjetoValor):
    id_comando: UUID
    instante: datetime
    correlacion: UUID
    causacion: UUID

    def __post_init__(self) -> None:
        for identidad in (self.id_comando, self.correlacion, self.causacion):
            validar_identidad(identidad)
        validar_instante(self.instante)


@dataclass(frozen=True, kw_only=True)
class OfertaCatalogo(ObjetoValor):
    id_proveedor: UUID
    categoria: str
    tipo_red: TipoRed
    id_partner: UUID | None
    precio: Dinero

    def __post_init__(self) -> None:
        try:
            self._validar()
        except ValueError as error:
            raise CatalogoInvalido(str(error)) from error

    def _validar(self) -> None:
        validar_identidad(self.id_proveedor)
        if not isinstance(self.categoria, str) or self.categoria != normalizar_categoria(
            self.categoria
        ):
            raise ValueError("La categoria de la oferta debe estar normalizada")
        if not isinstance(self.tipo_red, TipoRed):
            raise ValueError("Tipo de red invalido en la oferta")
        if not isinstance(self.precio, Dinero):
            raise ValueError("El precio de la oferta debe ser Dinero")
        if self.tipo_red is TipoRed.GENERAL_HDA and self.id_partner is not None:
            raise ValueError("Una oferta de red general no admite partner")
        if self.tipo_red is TipoRed.HOMOLOGADA_PARTNER:
            if self.id_partner is None:
                raise ValueError("Una oferta homologada requiere partner")
            validar_identidad(self.id_partner)


@dataclass(frozen=True, kw_only=True)
class CatalogoVigente(ObjetoValor):
    version: int
    ofertas: tuple[OfertaCatalogo, ...]

    def __post_init__(self) -> None:
        try:
            validar_version(self.version)
        except ValueError as error:
            raise CatalogoInvalido(str(error)) from error
        if not isinstance(self.ofertas, tuple) or not self.ofertas:
            raise CatalogoInvalido("El catalogo requiere una tupla con al menos una oferta")
        if not all(isinstance(oferta, OfertaCatalogo) for oferta in self.ofertas):
            raise CatalogoInvalido("El catalogo solo admite ofertas validas")
        combinaciones = {
            (oferta.categoria, oferta.tipo_red, oferta.id_partner, oferta.id_proveedor)
            for oferta in self.ofertas
        }
        if len(combinaciones) != len(self.ofertas):
            raise CatalogoInvalido("El catalogo contiene una oferta duplicada")

    def ofertas_de_categoria(self, clave: str) -> tuple[OfertaCatalogo, ...]:
        return tuple(oferta for oferta in self.ofertas if oferta.categoria == clave)


@dataclass(frozen=True, kw_only=True)
class ResultadoCotizacion(ObjetoValor):
    estado: EstadoCotizacion
    oferta: OfertaCatalogo | None = None
    motivo: MotivoRechazo | None = None

    def __post_init__(self) -> None:
        if self.estado is EstadoCotizacion.PROPUESTA:
            if not isinstance(self.oferta, OfertaCatalogo) or self.motivo is not None:
                raise ValueError("Una propuesta requiere oferta y ningun motivo de rechazo")
        elif self.estado is EstadoCotizacion.RECHAZADA:
            if self.oferta is not None or not isinstance(self.motivo, MotivoRechazo):
                raise ValueError("Un rechazo requiere motivo y ninguna oferta")
        else:
            raise ValueError("Estado de cotizacion invalido")
