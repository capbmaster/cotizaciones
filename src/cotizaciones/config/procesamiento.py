import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from cotizaciones.seedwork.infraestructura.ciclos import (
    EstadoComponente,
    Procesamiento,
    iniciar_ciclo,
)
from cotizaciones.seedwork.infraestructura.despacho_outbox import DespachadorOutbox

if TYPE_CHECKING:
    from cotizaciones.config.database import Database
    from cotizaciones.config.settings import Settings

# Presupuesto total de cierre de los ciclos: el proceso completo debe cerrar en menos de 10 s.
PRESUPUESTO_CIERRE_SEGUNDOS = 9.0
_registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class EstadoMensajeria:
    componentes: tuple[EstadoComponente, ...] = ()
    procesamientos: tuple[Procesamiento, ...] = ()

    def en_ejecucion(self) -> bool:
        return any(procesamiento.hilo.is_alive() for procesamiento in self.procesamientos)

    def listo(self) -> bool:
        return all(componente.esta_operando() for componente in self.componentes)

    def resumen(self) -> dict[str, dict[str, str | None]]:
        return {componente.nombre: componente.resumen() for componente in self.componentes}


def detener_procesamientos(
    procesamientos: Sequence[Procesamiento], presupuesto: float = PRESUPUESTO_CIERRE_SEGUNDOS
) -> None:
    """Señala a todos a la vez y los espera dentro de un presupuesto compartido."""
    for procesamiento in procesamientos:
        procesamiento.senalar()
    limite = monotonic() + presupuesto
    sin_terminar = []
    for procesamiento in procesamientos:
        try:
            procesamiento.detener(max(0.0, limite - monotonic()))
        except TimeoutError:
            sin_terminar.append(procesamiento.hilo.name)
    if sin_terminar:
        raise TimeoutError(f"Ciclos sin terminar dentro del presupuesto de cierre: {sin_terminar}")


@asynccontextmanager
async def procesar_mensajeria(
    base: "Database", configuracion: "Settings"
) -> AsyncIterator[EstadoMensajeria]:
    """Consumo de peticiones y despacho de resultados en hilos propios del mismo proceso."""
    from cotizaciones.config.bootstrap import (
        componer_consumidor_peticiones,
        componer_despacho_resultados,
    )
    from cotizaciones.config.persistencia import verificar_destinos

    await asyncio.to_thread(verificar_destinos, base)
    consumo = EstadoComponente("consumo-peticiones")
    despacho = EstadoComponente(NOMBRE_DESPACHO)
    consumidor = componer_consumidor_peticiones(base, configuracion)
    despachador, cerrar_publicador = componer_despacho_resultados(base, configuracion)
    procesamientos: list[Procesamiento] = []
    try:
        procesamientos.append(
            iniciar_ciclo(
                consumidor.procesar_siguiente, consumo.nombre, consumo, cerrar=consumidor.cerrar
            )
        )
        procesamientos.append(iniciar_despacho(despachador, despacho, cerrar=cerrar_publicador))
        yield EstadoMensajeria((consumo, despacho), tuple(procesamientos))
    finally:
        # Nunca ACK ni marcas del outbox como parte del apagado; tampoco unsubscribe.
        await asyncio.to_thread(detener_procesamientos, procesamientos)


NOMBRE_DESPACHO = "despacho-resultados"
LOTE = 1


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
        if despachador.ultimo_error is not None:
            raise ErrorPublicacion(despachador.ultimo_error)
        return confirmadas > 0

    return iniciar_ciclo(
        paso, NOMBRE_DESPACHO, estado, pausa_inactiva=pausa_inactiva, cerrar=cerrar
    )
