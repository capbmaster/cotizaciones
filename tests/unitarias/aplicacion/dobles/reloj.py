from dataclasses import dataclass
from datetime import datetime

from ...dominio.datos import INSTANTE_RESULTADO


@dataclass
class RelojFijo:
    instante: datetime = INSTANTE_RESULTADO

    def ahora(self) -> datetime:
        return self.instante
