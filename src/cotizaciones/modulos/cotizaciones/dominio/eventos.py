from dataclasses import dataclass
from uuid import UUID

from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    DatosPeticion,
    Dinero,
    MotivoRechazo,
)
from cotizaciones.seedwork.dominio.eventos import EventoDominio
from cotizaciones.seedwork.dominio.validaciones import validar_identidad, validar_version


@dataclass(frozen=True, kw_only=True)
class _ResolucionCotizacion(EventoDominio):
    id_cotizacion: UUID
    peticion: DatosPeticion
    id_comando: UUID
    correlacion: UUID
    version_catalogo: int
    version_cotizacion: int

    def __post_init__(self) -> None:
        super().__post_init__()
        for identidad in (self.id_cotizacion, self.id_comando, self.correlacion):
            validar_identidad(identidad)
        if not isinstance(self.peticion, DatosPeticion):
            raise ValueError("El hecho requiere los datos de la peticion")
        validar_version(self.version_catalogo)
        validar_version(self.version_cotizacion)


@dataclass(frozen=True, kw_only=True)
class CotizacionRegistrada(_ResolucionCotizacion):
    id_proveedor: UUID
    precio: Dinero

    def __post_init__(self) -> None:
        super().__post_init__()
        validar_identidad(self.id_proveedor)
        if not isinstance(self.precio, Dinero):
            raise ValueError("La propuesta requiere un precio en Dinero")


@dataclass(frozen=True, kw_only=True)
class CotizacionRechazada(_ResolucionCotizacion):
    motivo: MotivoRechazo

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.motivo, MotivoRechazo):
            raise ValueError("El rechazo requiere un motivo valido")
