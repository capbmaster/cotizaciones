from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente
from cotizaciones.seedwork.aplicacion.excepciones import ColisionPersistencia


def _sin_efecto(*argumentos: object) -> None:
    return None


@dataclass
class RepositorioCotizacionesMemoria:
    por_peticion: dict[UUID, Cotizacion]
    antes_de_guardar: Callable[[Cotizacion], None] = _sin_efecto

    def obtener_por_peticion(self, id_peticion: UUID) -> Cotizacion | None:
        return self.por_peticion.get(id_peticion)

    def guardar(self, cotizacion: Cotizacion) -> None:
        self.antes_de_guardar(cotizacion)
        # Imita la restricción UNIQUE uq_cotizacion_peticion de PostgreSQL.
        if cotizacion.peticion.id_peticion in self.por_peticion:
            raise ColisionPersistencia("uq_cotizacion_peticion")
        self.por_peticion[cotizacion.peticion.id_peticion] = cotizacion


@dataclass
class RepositorioCatalogoMemoria:
    vigente: CatalogoVigente | None
    al_consultar: Callable[[], None] = _sin_efecto

    def obtener_vigente(self) -> CatalogoVigente | None:
        self.al_consultar()
        return self.vigente
