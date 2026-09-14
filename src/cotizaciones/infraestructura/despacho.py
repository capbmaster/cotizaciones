from collections.abc import Callable

from cotizaciones.seedwork.infraestructura.ciclos import (
    EstadoComponente,
    Procesamiento,
    iniciar_ciclo,
)
from cotizaciones.seedwork.infraestructura.despacho_outbox import DespachadorOutbox

NOMBRE_DESPACHO = "despacho-resultados"
LOTE = 20


class ErrorPublicacion(RuntimeError):
    """Ninguna salida se confirmó y la última falló; ya quedó reprogramada en el outbox."""


def iniciar_despacho(
    despachador: DespachadorOutbox,
    estado: EstadoComponente,
    cerrar: Callable[[], None] = lambda: None,
    pausa_inactiva: float = 0.2,
) -> Procesamiento:
    def paso() -> bool:
        confirmadas = despachador.despachar_lote(LOTE)
        if confirmadas == 0 and despachador.ultimo_error is not None:
            raise ErrorPublicacion(despachador.ultimo_error)
        return confirmadas > 0

    return iniciar_ciclo(
        paso, NOMBRE_DESPACHO, estado, pausa_inactiva=pausa_inactiva, cerrar=cerrar
    )
