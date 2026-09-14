from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True)
class Publicacion:
    id: UUID
    id_evento: UUID
    destino: str
    documento: dict[str, Any]


class Publicador(Protocol):
    def publicar(self, publicacion: Publicacion) -> bool: ...
