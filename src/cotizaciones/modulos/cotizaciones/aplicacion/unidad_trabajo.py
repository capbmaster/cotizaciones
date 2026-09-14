from typing import Protocol

from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.dominio.repositorios import (
    RepositorioCatalogo,
    RepositorioCotizaciones,
)
from cotizaciones.seedwork.aplicacion.unidad_trabajo import UnidadTrabajo


class UnidadTrabajoCotizaciones(UnidadTrabajo, Protocol):
    @property
    def cotizaciones(self) -> RepositorioCotizaciones: ...

    @property
    def catalogos(self) -> RepositorioCatalogo: ...

    def registrar_recepcion(self, consumidor: str, comando: ProcesarPeticionCotizacion) -> bool:
        """Verdadero si la marca (consumidor, id_comando) es nueva; falso si ya existía igual.

        Lanza ConflictoMensaje si existía con otro contenido. Participa de la misma
        transacción que el efecto.
        """
        ...
