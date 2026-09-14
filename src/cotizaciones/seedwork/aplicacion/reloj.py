from datetime import datetime
from typing import Protocol


class Reloj(Protocol):
    def ahora(self) -> datetime: ...
