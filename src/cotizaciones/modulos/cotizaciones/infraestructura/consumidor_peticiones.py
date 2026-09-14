import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.aplicacion.excepciones import ConflictoPeticion
from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ResultadoProcesamiento,
)
from cotizaciones.seedwork.aplicacion.excepciones import ConflictoMensaje
from cotizaciones.seedwork.infraestructura.ciclos import MensajeVenenoso

_registro = logging.getLogger(__name__)
TIMEOUT_RECEPCION_MS = 1000


class ConsumidorPeticiones:
    """Consume SolicitarCotizacion.v1 (Shared) y hace ACK solo después del commit del handler."""

    def __init__(
        self,
        url: str,
        topico: str,
        suscripcion: str,
        procesar: Callable[[ProcesarPeticionCotizacion], ResultadoProcesamiento],
        *,
        tamano_cola: int = 1,
        demora_nack_ms: int = 5000,
        timeout_segundos: int = 3,
        retardo_laboratorio_ms: int = 0,
        crear_cliente: Callable[..., Any] | None = None,
        esperar: Callable[[float], None] = time.sleep,
    ) -> None:
        if not topico.startswith("persistent://") or not suscripcion.strip():
            raise ValueError("El consumo requiere topico persistente y suscripcion")
        if tamano_cola <= 0 or demora_nack_ms <= 0 or timeout_segundos <= 0:
            raise ValueError("Cola, demora de NACK y timeout deben ser positivos")
        if retardo_laboratorio_ms < 0:
            raise ValueError("El retardo de laboratorio no puede ser negativo")
        self.url = url
        self.topico = topico
        self.suscripcion = suscripcion
        self.procesar = procesar
        self.tamano_cola = tamano_cola
        self.demora_nack_ms = demora_nack_ms
        self.timeout_segundos = timeout_segundos
        self.retardo_laboratorio_ms = retardo_laboratorio_ms
        self.crear_cliente = crear_cliente
        self.esperar = esperar
        self._cliente: Any = None
        self._consumidor: Any = None

    def abrir(self) -> None:
        if self._consumidor is not None:
            return
        import pulsar
        from pulsar.schema import AvroSchema

        from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
            SolicitarCotizacionV1,
        )

        crear = self.crear_cliente or pulsar.Client
        self._cliente = crear(
            self.url,
            operation_timeout_seconds=self.timeout_segundos,
            connection_timeout_ms=self.timeout_segundos * 1000,
        )
        try:
            self._consumidor = self._cliente.subscribe(
                self.topico,
                self.suscripcion,
                schema=AvroSchema(SolicitarCotizacionV1),
                consumer_type=pulsar.ConsumerType.Shared,
                initial_position=pulsar.InitialPosition.Earliest,
                receiver_queue_size=self.tamano_cola,
                negative_ack_redelivery_delay_ms=self.demora_nack_ms,
            )
        except Exception:
            self.cerrar()
            raise

    def procesar_siguiente(self) -> bool:
        import pulsar

        from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
            comando_desde_mensaje,
        )

        self.abrir()
        try:
            mensaje = self._consumidor.receive(timeout_millis=TIMEOUT_RECEPCION_MS)
        except pulsar.Timeout:
            return False
        id_mensaje = self._identificador(mensaje)
        try:
            comando = comando_desde_mensaje(mensaje.value())
        except Exception as error:
            raise MensajeVenenoso(id_mensaje, f"{type(error).__name__}: {error}") from error
        if self.retardo_laboratorio_ms > 0:
            _registro.info("Retardo SINTETICO de laboratorio: %d ms", self.retardo_laboratorio_ms)
            self.esperar(self.retardo_laboratorio_ms / 1000)
        try:
            resultado = self.procesar(comando)
        except (ConflictoPeticion, ConflictoMensaje) as error:
            raise MensajeVenenoso(id_mensaje, f"{type(error).__name__}: {error}") from error
        except Exception:
            self._consumidor.negative_acknowledge(mensaje)
            raise
        self._consumidor.acknowledge(mensaje)
        latencia = (datetime.now(UTC) - comando.origen.instante).total_seconds()
        _registro.info(
            "Peticion %s: cotizacion %s, nueva=%s, latencia comando->efecto %.3f s "
            "(medida distribuida; puede incluir desfase de relojes)",
            comando.datos.id_peticion,
            resultado.id_cotizacion,
            resultado.nueva,
            latencia,
        )
        return True

    def cerrar(self) -> None:
        """Cierra el cliente sin anular la suscripción: los pendientes siguen en el broker."""
        cliente = self._cliente
        self._cliente = None
        self._consumidor = None
        if cliente is not None:
            cliente.close()

    @staticmethod
    def _identificador(mensaje: Any) -> str:
        try:
            propiedades = mensaje.properties() or {}
        except Exception:
            propiedades = {}
        return str(propiedades.get("command_id") or mensaje.message_id())
