from datetime import UTC, datetime
from typing import Any
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from cotizaciones.config.rutas import DESTINO_RECHAZADA, DESTINO_REGISTRADA
from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
    mensaje_rechazada,
    mensaje_registrada,
)
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import serializar_evento
from cotizaciones.seedwork.aplicacion.publicacion import Publicacion
from cotizaciones.seedwork.infraestructura.despacho_outbox import DespachadorOutbox
from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox, Reserva
from cotizaciones.seedwork.infraestructura.publicador_pulsar import (
    DestinoPulsar,
    PublicadorPulsar,
)

from .dominio.datos import ID_TRABAJO, cotizacion_resuelta, uuid_lab

URL = "pulsar://pulsar:6650"
TOPICO_REGISTRADA = "persistent://public/default/prueba-registrada"
TOPICO_RECHAZADA = "persistent://public/default/prueba-rechazada"


def publicacion(destino: str = DESTINO_REGISTRADA, **cambios_peticion: Any) -> Publicacion:
    (evento,) = cotizacion_resuelta(**cambios_peticion).retirar_eventos()
    return Publicacion(uuid4(), evento.id_evento, destino, serializar_evento(evento))


def rechazo() -> Publicacion:
    (evento,) = cotizacion_resuelta(
        categoria="jardineria", id_evento=uuid_lab("0032")
    ).retirar_eventos()
    return Publicacion(uuid4(), evento.id_evento, DESTINO_RECHAZADA, serializar_evento(evento))


def clave(mensaje: Any) -> str:
    return str(mensaje.id_trabajo)


def publicador(crear_cliente: Mock) -> PublicadorPulsar:
    return PublicadorPulsar(
        URL,
        {
            DESTINO_REGISTRADA: DestinoPulsar(
                TOPICO_REGISTRADA, "esquema-registrada", mensaje_registrada, clave
            ),
            DESTINO_RECHAZADA: DestinoPulsar(
                TOPICO_RECHAZADA, "esquema-rechazada", mensaje_rechazada, clave
            ),
        },
        timeout_segundos=3,
        crear_cliente=crear_cliente,
    )


def cliente_falso() -> tuple[Mock, dict[str, Mock]]:
    productores: dict[str, Mock] = {}
    crear = Mock()
    crear.return_value.create_producer.side_effect = lambda topico, **_: productores.setdefault(
        topico, Mock()
    )
    return crear, productores


def test_construir_no_crea_cliente() -> None:
    crear, _ = cliente_falso()
    publicador(crear)
    crear.assert_not_called()


def test_un_productor_por_topico_reutilizado_con_clave_y_propiedades() -> None:
    crear, productores = cliente_falso()
    salida = publicador(crear)
    propuesta = publicacion()
    assert salida.publicar(propuesta) is True
    assert salida.publicar(propuesta) is True
    assert salida.publicar(rechazo()) is True
    crear.assert_called_once_with(URL, operation_timeout_seconds=3, connection_timeout_ms=3000)
    llamadas = crear.return_value.create_producer.call_args_list
    assert [llamada.args[0] for llamada in llamadas] == [TOPICO_REGISTRADA, TOPICO_RECHAZADA]
    assert llamadas[0].kwargs == {
        "schema": "esquema-registrada",
        "send_timeout_millis": 3000,
        "batching_enabled": False,
        "max_pending_messages": 1,
    }
    envio = productores[TOPICO_REGISTRADA].send
    assert envio.call_count == 2
    mensaje = envio.call_args.args[0]
    assert mensaje.event_id == str(propuesta.id_evento)
    assert envio.call_args.kwargs == {
        "partition_key": str(ID_TRABAJO),
        "properties": {"event_id": str(propuesta.id_evento), "tipo": "CotizacionRegistrada.v1"},
    }
    assert productores[TOPICO_RECHAZADA].send.call_args.kwargs["properties"]["tipo"] == (
        "CotizacionRechazada.v1"
    )


def test_destino_desconocido_falla_sin_crear_cliente() -> None:
    crear, _ = cliente_falso()
    with pytest.raises(ValueError, match="Destino"):
        publicador(crear).publicar(publicacion(destino="laboratorio.anterior"))
    crear.assert_not_called()


def test_identidad_incoherente_falla_sin_enviar() -> None:
    crear, productores = cliente_falso()
    incoherente = Publicacion(uuid4(), UUID(int=77), DESTINO_REGISTRADA, publicacion().documento)
    with pytest.raises(ValueError, match="Identidad"):
        publicador(crear).publicar(incoherente)
    assert productores == {}


def test_un_error_de_envio_se_propaga() -> None:
    crear, productores = cliente_falso()
    salida = publicador(crear)
    salida.publicar(publicacion())
    productores[TOPICO_REGISTRADA].send.side_effect = RuntimeError("broker caido")
    with pytest.raises(RuntimeError, match="broker caido"):
        salida.publicar(publicacion())


def test_fallo_al_crear_el_productor_cierra_el_cliente() -> None:
    crear = Mock()
    crear.return_value.create_producer.side_effect = RuntimeError("sin broker")
    salida = publicador(crear)
    with pytest.raises(RuntimeError, match="sin broker"):
        salida.publicar(publicacion())
    crear.return_value.close.assert_called_once_with()
    with pytest.raises(RuntimeError):
        salida.publicar(publicacion())
    assert crear.call_count == 2


def test_cerrar_es_idempotente_y_el_siguiente_envio_crea_un_cliente_nuevo() -> None:
    crear, _ = cliente_falso()
    salida = publicador(crear)
    salida.publicar(publicacion())
    primer_cliente = crear.return_value
    salida.cerrar()
    salida.cerrar()
    primer_cliente.close.assert_called_once_with()
    salida.publicar(publicacion())
    assert crear.call_count == 2


@pytest.mark.parametrize(
    ("topico", "timeout"),
    [("non-persistent://public/default/x", 3), ("persistent://public/default/x", 0)],
)
def test_topico_no_persistente_o_timeout_no_positivo_falla(topico: str, timeout: int) -> None:
    with pytest.raises(ValueError):
        PublicadorPulsar(
            URL,
            {DESTINO_REGISTRADA: DestinoPulsar(topico, "e", mensaje_registrada, clave)},
            timeout_segundos=timeout,
        )


def test_el_despachador_registra_y_limpia_el_ultimo_error() -> None:
    outbox = Mock(spec=RepositorioOutbox)
    reserva = Reserva(publicacion(), uuid4(), "A", datetime.now(UTC))
    outbox.reclamar.return_value = [reserva]
    outbox.confirmar.return_value = True
    transporte = Mock()
    transporte.publicar.side_effect = RuntimeError("broker caido")
    despachador = DespachadorOutbox(outbox, transporte, "A")
    assert despachador.ultimo_error is None
    assert despachador.despachar_lote() == 0
    assert despachador.ultimo_error == "RuntimeError: broker caido"
    outbox.reprogramar.assert_called_once()
    transporte.publicar.side_effect = None
    transporte.publicar.return_value = True
    assert despachador.despachar_lote() == 1
    assert despachador.ultimo_error is None
