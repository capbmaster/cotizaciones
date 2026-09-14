from dataclasses import dataclass, field
from uuid import UUID

from cotizaciones.seedwork.dominio.eventos import EventoDominio
from cotizaciones.seedwork.dominio.validaciones import validar_identidad


@dataclass(frozen=True, eq=False, kw_only=True)
class Entidad:
    id: UUID

    def __post_init__(self) -> None:
        validar_identidad(self.id)

    def __eq__(self, otra: object) -> bool:
        if not isinstance(otra, Entidad):
            return NotImplemented
        return type(self) is type(otra) and self.id == otra.id

    def __hash__(self) -> int:
        return hash((type(self), self.id))


@dataclass(frozen=True, eq=False, kw_only=True)
class AgregacionRaiz(Entidad):
    _eventos_pendientes: tuple[EventoDominio, ...] = field(default=(), init=False, repr=False)

    @property
    def eventos_pendientes(self) -> tuple[EventoDominio, ...]:
        return self._eventos_pendientes

    def retirar_eventos(self) -> tuple[EventoDominio, ...]:
        pendientes = self._eventos_pendientes
        object.__setattr__(self, "_eventos_pendientes", ())
        return pendientes

    def _registrar_evento(self, evento: EventoDominio) -> None:
        object.__setattr__(self, "_eventos_pendientes", (*self._eventos_pendientes, evento))
