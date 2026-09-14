from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from cotizaciones.seedwork.aplicacion.publicacion import Publicacion
from cotizaciones.seedwork.infraestructura.serializacion import Documento


@dataclass(frozen=True)
class DestinoPulsar:
    topico: str
    esquema: Any
    convertir: Callable[[Documento], Any]
    clave: Callable[[Any], str]


class PublicadorPulsar:
    """Un cliente perezoso y un productor por tópico; `publicar` vuelve tras el acuse del broker."""

    def __init__(
        self,
        url: str,
        destinos: Mapping[str, DestinoPulsar],
        timeout_segundos: int = 3,
        crear_cliente: Callable[..., Any] | None = None,
    ) -> None:
        if timeout_segundos <= 0:
            raise ValueError("La publicacion requiere un timeout positivo")
        if not destinos or any(
            not destino.topico.startswith("persistent://") for destino in destinos.values()
        ):
            raise ValueError("La publicacion requiere destinos con topicos persistentes")
        self.url = url
        self.destinos = dict(destinos)
        self.timeout_segundos = timeout_segundos
        self.crear_cliente = crear_cliente
        self._cliente: Any = None
        self._productores: dict[str, Any] = {}

    def publicar(self, publicacion: Publicacion) -> bool:
        destino = self.destinos.get(publicacion.destino)
        if destino is None:
            raise ValueError(f"Destino desconocido: {publicacion.destino}")
        mensaje = destino.convertir(publicacion.documento)
        if mensaje.event_id != str(publicacion.id_evento):
            raise ValueError("Identidad de la salida incompatible con el evento publico")
        self._productor(destino).send(
            mensaje,
            partition_key=destino.clave(mensaje),
            properties={"event_id": mensaje.event_id, "tipo": mensaje.tipo},
        )
        return True

    def _productor(self, destino: DestinoPulsar) -> Any:
        productor = self._productores.get(destino.topico)
        if productor is not None:
            return productor
        try:
            if self._cliente is None:
                crear = self.crear_cliente
                if crear is None:
                    import pulsar

                    crear = pulsar.Client
                self._cliente = crear(
                    self.url,
                    operation_timeout_seconds=self.timeout_segundos,
                    connection_timeout_ms=self.timeout_segundos * 1000,
                )
            productor = self._cliente.create_producer(
                destino.topico,
                schema=destino.esquema,
                send_timeout_millis=self.timeout_segundos * 1000,
                batching_enabled=False,
                max_pending_messages=1,
            )
        except Exception:
            self.cerrar()
            raise
        self._productores[destino.topico] = productor
        return productor

    def cerrar(self) -> None:
        cliente = self._cliente
        self._cliente = None
        self._productores = {}
        if cliente is not None:
            cliente.close()
