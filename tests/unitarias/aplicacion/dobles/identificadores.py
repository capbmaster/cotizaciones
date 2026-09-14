from dataclasses import dataclass
from uuid import UUID


@dataclass
class IdentificadoresSecuenciales:
    siguiente: int = 100

    def generar(self) -> UUID:
        identidad = UUID(int=self.siguiente)
        self.siguiente += 1
        return identidad
