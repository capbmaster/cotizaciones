from dataclasses import dataclass, field
from datetime import timedelta

from cotizaciones.seedwork.aplicacion.publicacion import Publicador
from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox


@dataclass
class DespachadorOutbox:
    outbox: RepositorioOutbox
    publicador: Publicador
    propietario: str
    duracion: timedelta = timedelta(seconds=30)
    demora_reintento: timedelta = timedelta(seconds=5)
    # Se actualiza en cada fallo y se limpia en cada confirmación.
    ultimo_error: str | None = field(default=None, init=False)

    def despachar_lote(self, limite: int = 20) -> int:
        """Reserva hasta `limite` salidas, las publica y devuelve cuántas confirmó."""
        confirmadas = 0
        for reserva in self.outbox.reclamar(self.propietario, limite, self.duracion):
            try:
                if not self.publicador.publicar(reserva.publicacion):
                    raise RuntimeError("Publicacion sin acuse positivo")
            except Exception as error:
                self.ultimo_error = f"{type(error).__name__}: {error}"
                self.outbox.reprogramar(reserva, str(error), self.demora_reintento)
                continue
            if self.outbox.confirmar(reserva):
                confirmadas += 1
                self.ultimo_error = None
        return confirmadas
