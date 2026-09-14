from typing import Any
from unittest.mock import Mock

import pulsar
import pytest
from pulsar.schema import AvroSchema
from sqlalchemy.exc import OperationalError

from cotizaciones.modulos.cotizaciones.aplicacion.excepciones import ConflictoPeticion
from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ResultadoProcesamiento,
)
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoNoDisponible
from cotizaciones.modulos.cotizaciones.infraestructura.consumidor_peticiones import (
    ConsumidorPeticiones,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)
from cotizaciones.seedwork.aplicacion.excepciones import ConflictoMensaje
from cotizaciones.seedwork.infraestructura.ciclos import MensajeVenenoso

from .aplicacion.datos import MENSAJE_COMANDO_F1, comando_peticion
from .dominio.datos import ID_COTIZACION

TOPICO = "persistent://public/default/prueba-peticiones"
SUSCRIPCION = "cotizaciones-peticiones-v1"
ID_MENSAJE = MENSAJE_COMANDO_F1["command_id"]


def mensaje_pulsar(valor: Any = None, propiedades: dict[str, str] | None = None) -> Mock:
    mensaje = Mock()
    if isinstance(valor, BaseException):
        mensaje.value.side_effect = valor
    else:
        mensaje.value.return_value = valor or SolicitarCotizacionV1(**MENSAJE_COMANDO_F1)
    mensaje.properties.return_value = (
        {"command_id": ID_MENSAJE, "tipo": "SolicitarCotizacion.v1"}
        if propiedades is None
        else propiedades
    )
    mensaje.message_id.return_value = "10:3:-1"
    return mensaje


def preparar(
    mensaje: Mock, procesar: Mock | None = None, **opciones: Any
) -> tuple[ConsumidorPeticiones, Mock, Mock, Mock]:
    cliente = Mock()
    transporte = cliente.subscribe.return_value
    transporte.receive.return_value = mensaje
    procesar = procesar or Mock(
        return_value=ResultadoProcesamiento(id_cotizacion=ID_COTIZACION, nueva=True)
    )
    crear = Mock(return_value=cliente)
    consumidor = ConsumidorPeticiones(
        "pulsar://pulsar:6650", TOPICO, SUSCRIPCION, procesar, crear_cliente=crear, **opciones
    )
    return consumidor, crear, transporte, procesar


def test_ack_solo_despues_de_procesar_con_exito() -> None:
    pasos: list[str] = []
    mensaje = mensaje_pulsar()

    def confirmar(comando: Any) -> ResultadoProcesamiento:
        pasos.append("procesar")
        return ResultadoProcesamiento(id_cotizacion=ID_COTIZACION, nueva=True)

    procesar = Mock(side_effect=confirmar)
    consumidor, _, transporte, _ = preparar(mensaje, procesar)
    transporte.acknowledge.side_effect = lambda m: pasos.append("ack")
    assert consumidor.procesar_siguiente() is True
    assert pasos == ["procesar", "ack"]
    procesar.assert_called_once_with(comando_peticion())
    transporte.acknowledge.assert_called_once_with(mensaje)
    transporte.negative_acknowledge.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        CatalogoNoDisponible("sin catalogo activo"),
        OperationalError("SELECT 1", {}, Exception("base caida")),
    ],
    ids=["catalogo-ausente", "error-sql"],
)
def test_error_tecnico_hace_nack_y_se_propaga(error: Exception) -> None:
    mensaje = mensaje_pulsar()
    consumidor, _, transporte, _ = preparar(mensaje, Mock(side_effect=error))
    with pytest.raises(type(error)):
        consumidor.procesar_siguiente()
    transporte.negative_acknowledge.assert_called_once_with(mensaje)
    transporte.acknowledge.assert_not_called()


def test_mensaje_invalido_pausa_sin_ack_ni_nack_ni_procesar() -> None:
    mensaje = mensaje_pulsar(SolicitarCotizacionV1(**{**MENSAJE_COMANDO_F1, "tipo_red": "OTRA"}))
    consumidor, _, transporte, procesar = preparar(mensaje)
    with pytest.raises(MensajeVenenoso) as capturado:
        consumidor.procesar_siguiente()
    assert capturado.value.id_mensaje == ID_MENSAJE
    assert "tipo_red" in capturado.value.motivo
    procesar.assert_not_called()
    transporte.acknowledge.assert_not_called()
    transporte.negative_acknowledge.assert_not_called()


def test_fallo_al_decodificar_pausa_y_usa_el_message_id_si_no_hay_command_id() -> None:
    mensaje = mensaje_pulsar(RuntimeError("bytes Avro corruptos"), propiedades={})
    consumidor, _, transporte, procesar = preparar(mensaje)
    with pytest.raises(MensajeVenenoso) as capturado:
        consumidor.procesar_siguiente()
    assert capturado.value.id_mensaje == "10:3:-1"
    assert "corruptos" in capturado.value.motivo
    procesar.assert_not_called()
    transporte.acknowledge.assert_not_called()
    transporte.negative_acknowledge.assert_not_called()


@pytest.mark.parametrize(
    "conflicto",
    [ConflictoPeticion("otros datos"), ConflictoMensaje("otro contenido")],
    ids=["peticion", "mensaje"],
)
def test_conflicto_pausa_sin_ack_ni_nack(conflicto: Exception) -> None:
    consumidor, _, transporte, _ = preparar(mensaje_pulsar(), Mock(side_effect=conflicto))
    with pytest.raises(MensajeVenenoso) as capturado:
        consumidor.procesar_siguiente()
    assert type(conflicto).__name__ in capturado.value.motivo
    transporte.acknowledge.assert_not_called()
    transporte.negative_acknowledge.assert_not_called()


def test_timeout_de_recepcion_devuelve_falso_sin_procesar() -> None:
    consumidor, _, transporte, procesar = preparar(mensaje_pulsar())
    transporte.receive.side_effect = pulsar.Timeout
    assert consumidor.procesar_siguiente() is False
    procesar.assert_not_called()
    transporte.receive.assert_called_once_with(timeout_millis=1000)


def test_la_suscripcion_es_shared_desde_el_inicio_con_esquema_cola_y_demora() -> None:
    consumidor, crear, transporte, _ = preparar(
        mensaje_pulsar(), tamano_cola=1, demora_nack_ms=5000, timeout_segundos=3
    )
    consumidor.procesar_siguiente()
    consumidor.procesar_siguiente()
    crear.assert_called_once_with(
        "pulsar://pulsar:6650", operation_timeout_seconds=3, connection_timeout_ms=3000
    )
    cliente = crear.return_value
    cliente.subscribe.assert_called_once()
    llamada = cliente.subscribe.call_args
    assert llamada.args == (TOPICO, SUSCRIPCION)
    assert isinstance(llamada.kwargs["schema"], AvroSchema)
    assert llamada.kwargs["consumer_type"] == pulsar.ConsumerType.Shared
    assert llamada.kwargs["initial_position"] == pulsar.InitialPosition.Earliest
    assert llamada.kwargs["receiver_queue_size"] == 1
    assert llamada.kwargs["negative_ack_redelivery_delay_ms"] == 5000


def test_fallo_al_suscribirse_cierra_el_cliente_y_se_propaga() -> None:
    consumidor, crear, _, _ = preparar(mensaje_pulsar())
    crear.return_value.subscribe.side_effect = RuntimeError("broker inaccesible")
    with pytest.raises(RuntimeError, match="inaccesible"):
        consumidor.procesar_siguiente()
    crear.return_value.close.assert_called_once_with()


def test_cerrar_no_anula_la_suscripcion_y_es_idempotente() -> None:
    consumidor, crear, transporte, _ = preparar(mensaje_pulsar())
    consumidor.procesar_siguiente()
    consumidor.cerrar()
    consumidor.cerrar()
    crear.return_value.close.assert_called_once_with()
    transporte.unsubscribe.assert_not_called()


def test_retardo_de_laboratorio_espera_antes_de_procesar() -> None:
    esperar = Mock()
    consumidor, _, _, _ = preparar(mensaje_pulsar(), retardo_laboratorio_ms=250, esperar=esperar)
    assert consumidor.procesar_siguiente() is True
    esperar.assert_called_once_with(0.25)


@pytest.mark.parametrize(
    "opciones",
    [
        {"topico": "non-persistent://public/default/x"},
        {"suscripcion": "  "},
        {"tamano_cola": 0},
        {"demora_nack_ms": 0},
        {"timeout_segundos": 0},
        {"retardo_laboratorio_ms": -1},
    ],
)
def test_configuracion_invalida_falla(opciones: dict[str, Any]) -> None:
    argumentos: dict[str, Any] = {"topico": TOPICO, "suscripcion": SUSCRIPCION, **opciones}
    with pytest.raises(ValueError):
        ConsumidorPeticiones(
            "pulsar://pulsar:6650",
            argumentos.pop("topico"),
            argumentos.pop("suscripcion"),
            Mock(),
            **argumentos,
        )
