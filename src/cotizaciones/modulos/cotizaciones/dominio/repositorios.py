from typing import Protocol
from uuid import UUID

from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente


class RepositorioCotizaciones(Protocol):
    def obtener_por_peticion(self, id_peticion: UUID) -> Cotizacion | None: ...

    def guardar(self, cotizacion: Cotizacion) -> None: ...


class RepositorioCatalogo(Protocol):
    def obtener_vigente(self) -> CatalogoVigente | None: ...
