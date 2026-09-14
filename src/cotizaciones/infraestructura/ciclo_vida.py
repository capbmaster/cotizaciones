import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from cotizaciones.seedwork.infraestructura.ciclos import (
    EstadoComponente,
    Procesamiento,
    iniciar_ciclo,
)

if TYPE_CHECKING:
    from cotizaciones.config.database import Database
    from cotizaciones.config.settings import Settings

# Presupuesto total de cierre de los ciclos: el proceso completo debe cerrar en menos de 10 s.
PRESUPUESTO_CIERRE_SEGUNDOS = 9.0
_registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class EstadoMensajeria:
    componentes: tuple[EstadoComponente, ...] = ()

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
    from cotizaciones.infraestructura.despacho import NOMBRE_DESPACHO, iniciar_despacho

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
        yield EstadoMensajeria((consumo, despacho))
    finally:
        # Nunca ACK ni marcas del outbox como parte del apagado; tampoco unsubscribe.
        await asyncio.to_thread(detener_procesamientos, procesamientos)
