from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cotizaciones.config.database import Database
    from cotizaciones.config.settings import Settings


class EstadoCiclo(StrEnum):
    INICIANDO = "INICIANDO"
    OPERANDO = "OPERANDO"
    REINTENTANDO = "REINTENTANDO"
    PAUSADO = "PAUSADO"
    DETENIDO = "DETENIDO"


@dataclass
class EstadoComponente:
    nombre: str
    estado: EstadoCiclo = EstadoCiclo.INICIANDO
    ultimo_error: str | None = None
    id_mensaje_pausa: str | None = None
    motivo_pausa: str | None = None

    def resumen(self) -> dict[str, str | None]:
        return {
            "estado": self.estado.value,
            "ultimo_error": self.ultimo_error,
            "id_mensaje_pausa": self.id_mensaje_pausa,
            "motivo_pausa": self.motivo_pausa,
        }


@dataclass(frozen=True)
class EstadoMensajeria:
    componentes: tuple[EstadoComponente, ...] = ()

    def listo(self) -> bool:
        return all(componente.estado is EstadoCiclo.OPERANDO for componente in self.componentes)

    def resumen(self) -> dict[str, dict[str, str | None]]:
        return {componente.nombre: componente.resumen() for componente in self.componentes}


@asynccontextmanager
async def procesar_mensajeria(
    base: "Database", configuracion: "Settings"
) -> AsyncIterator[EstadoMensajeria]:
    yield EstadoMensajeria()
