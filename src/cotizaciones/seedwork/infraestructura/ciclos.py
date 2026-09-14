import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import Event, Lock, Thread

_registro = logging.getLogger(__name__)


class EstadoCiclo(StrEnum):
    INICIANDO = "INICIANDO"
    OPERANDO = "OPERANDO"
    REINTENTANDO = "REINTENTANDO"
    PAUSADO = "PAUSADO"
    DETENIDO = "DETENIDO"


@dataclass
class EstadoComponente:
    """Estado observable de un ciclo: lo escribe su hilo y lo lee el hilo HTTP."""

    nombre: str
    estado: EstadoCiclo = EstadoCiclo.INICIANDO
    ultimo_error: str | None = None
    id_mensaje_pausa: str | None = None
    motivo_pausa: str | None = None
    ultimo_exito: datetime | None = None
    _candado: Lock = field(default_factory=Lock, init=False, repr=False, compare=False)

    def marcar_iniciando(self) -> None:
        with self._candado:
            self.estado = EstadoCiclo.INICIANDO
            self.id_mensaje_pausa = None
            self.motivo_pausa = None

    def marcar_operando(self) -> None:
        with self._candado:
            self.estado = EstadoCiclo.OPERANDO
            self.ultimo_exito = datetime.now(UTC)

    def marcar_reintentando(self, error: BaseException) -> None:
        with self._candado:
            self.estado = EstadoCiclo.REINTENTANDO
            self.ultimo_error = f"{type(error).__name__}: {error}"

    def marcar_pausado(self, id_mensaje: str, motivo: str) -> None:
        with self._candado:
            self.estado = EstadoCiclo.PAUSADO
            self.id_mensaje_pausa = id_mensaje
            self.motivo_pausa = motivo
            self.ultimo_error = motivo

    def marcar_detenido(self) -> None:
        with self._candado:
            self.estado = EstadoCiclo.DETENIDO

    def esta_operando(self) -> bool:
        with self._candado:
            return self.estado is EstadoCiclo.OPERANDO

    def resumen(self) -> dict[str, str | None]:
        with self._candado:
            return {
                "estado": self.estado.value,
                "ultimo_error": self.ultimo_error,
                "id_mensaje_pausa": self.id_mensaje_pausa,
                "motivo_pausa": self.motivo_pausa,
                "ultimo_exito": self.ultimo_exito.isoformat() if self.ultimo_exito else None,
            }


class MensajeVenenoso(Exception):
    """Mensaje inválido o contradictorio: se conserva sin ACK y se pausa el ciclo."""

    def __init__(self, id_mensaje: str, motivo: str) -> None:
        super().__init__(f"Mensaje {id_mensaje} pausado: {motivo}")
        self.id_mensaje = id_mensaje
        self.motivo = motivo


@dataclass
class Procesamiento:
    detener_senal: Event
    hilo: Thread

    def senalar(self) -> None:
        self.detener_senal.set()

    def detener(self, plazo: float = 8.0) -> None:
        self.detener_senal.set()
        self.hilo.join(plazo)
        if self.hilo.is_alive():
            raise TimeoutError(f"El ciclo {self.hilo.name} no termino dentro de {plazo:.1f} s")


def iniciar_ciclo(
    ejecutar_paso: Callable[[], bool],
    nombre: str,
    estado: EstadoComponente,
    pausa_inactiva: float = 0.2,
    espera_maxima_error: float = 5.0,
    cerrar: Callable[[], None] = lambda: None,
) -> Procesamiento:
    """Ejecuta `ejecutar_paso` en un hilo no daemon; solo pausa cuando no hubo trabajo."""
    if pausa_inactiva <= 0 or espera_maxima_error <= 0:
        raise ValueError("Las esperas del ciclo deben ser positivas")
    detener = Event()

    def ejecutar() -> None:
        estado.marcar_iniciando()
        fallos = 0
        try:
            while not detener.is_set():
                try:
                    hubo_trabajo = ejecutar_paso()
                except MensajeVenenoso as error:
                    estado.marcar_pausado(error.id_mensaje, error.motivo)
                    _registro.error(
                        "Ciclo %s pausado por el mensaje %s: %s",
                        nombre,
                        error.id_mensaje,
                        error.motivo,
                    )
                    detener.wait()
                    break
                except Exception as error:
                    fallos += 1
                    estado.marcar_reintentando(error)
                    _registro.exception("Fallo en el ciclo %s (intento %d)", nombre, fallos)
                    detener.wait(min(espera_maxima_error, 0.2 * 2**fallos))
                    continue
                estado.marcar_operando()
                fallos = 0
                if not hubo_trabajo:
                    detener.wait(pausa_inactiva)
        finally:
            try:
                cerrar()
            finally:
                estado.marcar_detenido()

    hilo = Thread(target=ejecutar, name=nombre, daemon=False)
    procesamiento = Procesamiento(detener, hilo)
    hilo.start()
    return procesamiento
