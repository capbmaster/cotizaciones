from collections.abc import Callable

from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ProcesarPeticionHandler,
)
from cotizaciones.modulos.cotizaciones.aplicacion.unidad_trabajo import (
    UnidadTrabajoCotizaciones,
)
from cotizaciones.seedwork.aplicacion.identificadores import GeneradorIdentificadores
from cotizaciones.seedwork.aplicacion.reloj import Reloj


def componer_procesamiento(
    crear_unidad: Callable[[], UnidadTrabajoCotizaciones],
    reloj: Reloj,
    identificadores: GeneradorIdentificadores,
) -> ProcesarPeticionHandler:
    return ProcesarPeticionHandler(crear_unidad, reloj, identificadores)
