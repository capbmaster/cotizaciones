from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    EstadoCotizacion,
    MotivoRechazo,
    TipoRed,
    TipoSolicitud,
)


@dataclass(frozen=True, kw_only=True)
class VistaCotizacion:
    """DTO de lectura, nunca el agregado: serializable directamente por FastAPI."""

    id_cotizacion: UUID
    id_peticion: UUID
    id_trabajo: UUID
    id_solicitud: UUID
    id_partner: UUID
    categoria: str
    tipo_solicitud: TipoSolicitud
    tipo_red: TipoRed
    estado: EstadoCotizacion
    id_proveedor: UUID | None
    importe_menor: int | None
    moneda: str | None
    motivo: MotivoRechazo | None
    version_catalogo: int
    version_cotizacion: int
    id_comando_origen: UUID
    resuelta_en: datetime


@dataclass(frozen=True, kw_only=True)
class FiltroCotizaciones:
    id_peticion: UUID | None = None
    id_trabajo: UUID | None = None
    estado: EstadoCotizacion | None = None


class RepositorioLecturaCotizaciones(Protocol):
    def obtener(self, id_cotizacion: UUID) -> VistaCotizacion | None: ...

    def listar(
        self, filtro: FiltroCotizaciones, limite: int, desplazamiento: int
    ) -> list[VistaCotizacion]: ...
