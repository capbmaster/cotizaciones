from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from cotizaciones.seedwork.dominio.validaciones import validar_identidad, validar_instante


@dataclass(frozen=True, kw_only=True)
class EventoDominio:
    id_evento: UUID
    instante: datetime

    def __post_init__(self) -> None:
        validar_identidad(self.id_evento)
        validar_instante(self.instante)
