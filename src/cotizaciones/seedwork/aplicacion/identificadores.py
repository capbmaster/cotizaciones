from typing import Protocol
from uuid import UUID


class GeneradorIdentificadores(Protocol):
    def generar(self) -> UUID: ...
