from types import TracebackType
from typing import Protocol, Self

from cotizaciones.seedwork.dominio.eventos import EventoDominio


class UnidadTrabajo(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        tipo_error: type[BaseException] | None,
        error: BaseException | None,
        traza: TracebackType | None,
    ) -> None: ...

    def confirmar(self) -> None: ...

    def revertir(self) -> None: ...

    def registrar_salida(self, evento: EventoDominio) -> None: ...
