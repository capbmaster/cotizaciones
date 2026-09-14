from dataclasses import dataclass
from uuid import UUID

from cotizaciones.modulos.cotizaciones.aplicacion.consultas import (
    FiltroCotizaciones,
    RepositorioLecturaCotizaciones,
    VistaCotizacion,
)

LIMITE_MINIMO = 1
LIMITE_MAXIMO = 100


@dataclass(frozen=True)
class ConsultarCotizacionHandler:
    repositorio: RepositorioLecturaCotizaciones

    def __call__(self, id_cotizacion: UUID) -> VistaCotizacion | None:
        return self.repositorio.obtener(id_cotizacion)


@dataclass(frozen=True)
class ListarCotizacionesHandler:
    repositorio: RepositorioLecturaCotizaciones

    def __call__(
        self, filtro: FiltroCotizaciones, limite: int = 20, desplazamiento: int = 0
    ) -> list[VistaCotizacion]:
        if not LIMITE_MINIMO <= limite <= LIMITE_MAXIMO or desplazamiento < 0:
            raise ValueError("Paginacion invalida")
        return self.repositorio.listar(filtro, limite, desplazamiento)
