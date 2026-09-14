from collections.abc import Callable
from typing import TYPE_CHECKING

from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ProcesarPeticionHandler,
)
from cotizaciones.modulos.cotizaciones.aplicacion.unidad_trabajo import (
    UnidadTrabajoCotizaciones,
)
from cotizaciones.seedwork.aplicacion.identificadores import GeneradorIdentificadores
from cotizaciones.seedwork.aplicacion.reloj import Reloj
from cotizaciones.seedwork.infraestructura.identificadores import IdentificadoresAleatorios
from cotizaciones.seedwork.infraestructura.reloj import RelojActual

if TYPE_CHECKING:
    from cotizaciones.config.database import Database


def componer_procesamiento(
    crear_unidad: Callable[[], UnidadTrabajoCotizaciones],
    reloj: Reloj,
    identificadores: GeneradorIdentificadores,
) -> ProcesarPeticionHandler:
    return ProcesarPeticionHandler(crear_unidad, reloj, identificadores)


def componer_procesamiento_sql(base: "Database") -> ProcesarPeticionHandler:
    from cotizaciones.config.persistencia import crear_uow_cotizaciones

    return componer_procesamiento(
        lambda: crear_uow_cotizaciones(base), RelojActual(), IdentificadoresAleatorios()
    )
