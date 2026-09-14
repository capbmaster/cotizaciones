from cotizaciones.modulos.cotizaciones.dominio.eventos import (
    CotizacionRechazada,
    CotizacionRegistrada,
)
from cotizaciones.seedwork.dominio.eventos import EventoDominio

DESTINO_REGISTRADA = "integracion.cotizacion_registrada.v1"
DESTINO_RECHAZADA = "integracion.cotizacion_rechazada.v1"
DESTINOS_ADMITIDOS = (DESTINO_REGISTRADA, DESTINO_RECHAZADA)

_RUTAS: dict[type[EventoDominio], tuple[str, ...]] = {
    CotizacionRegistrada: (DESTINO_REGISTRADA,),
    CotizacionRechazada: (DESTINO_RECHAZADA,),
}


def destinos_evento(evento: EventoDominio) -> tuple[str, ...]:
    try:
        return _RUTAS[type(evento)]
    except KeyError as error:
        raise ValueError(f"Evento sin ruta definida: {type(evento).__name__}") from error
