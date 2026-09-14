import threading
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

import pytest

from cotizaciones.seedwork.infraestructura.ciclos import (
    EstadoCiclo,
    EstadoComponente,
    MensajeVenenoso,
    iniciar_ciclo,
)


def esperar(condicion: Callable[[], bool], segundos: float = 2.0) -> None:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return
        time.sleep(0.005)
    raise AssertionError("La condicion no se cumplio dentro del plazo")


def test_con_trabajo_no_se_pausa_entre_pasos() -> None:
    llamadas = 0

    def paso() -> bool:
        nonlocal llamadas
        llamadas += 1
        return True

    ciclo = iniciar_ciclo(paso, "prueba-con-trabajo", EstadoComponente("prueba"), pausa_inactiva=5)
    try:
        esperar(lambda: llamadas >= 50, segundos=1)
    finally:
        ciclo.detener()


def test_sin_trabajo_se_pausa_entre_pasos() -> None:
    llamadas = 0

    def paso() -> bool:
        nonlocal llamadas
        llamadas += 1
        return False

    ciclo = iniciar_ciclo(
        paso, "prueba-sin-trabajo", EstadoComponente("prueba"), pausa_inactiva=0.2
    )
    try:
        time.sleep(0.5)
    finally:
        ciclo.detener()
    assert 1 <= llamadas <= 4


def test_un_error_pasa_a_reintentando_y_el_siguiente_exito_vuelve_a_operando() -> None:
    estado = EstadoComponente("prueba")
    observados: list[EstadoCiclo] = []

    def paso() -> bool:
        observados.append(estado.estado)
        if len(observados) == 1:
            raise RuntimeError("base caida")
        return False

    ciclo = iniciar_ciclo(
        paso, "prueba-reintento", estado, pausa_inactiva=0.01, espera_maxima_error=0.01
    )
    try:
        esperar(lambda: len(observados) >= 3)
    finally:
        ciclo.detener()
    assert observados[:3] == [EstadoCiclo.INICIANDO, EstadoCiclo.REINTENTANDO, EstadoCiclo.OPERANDO]
    assert estado.ultimo_error == "RuntimeError: base caida"
    assert estado.ultimo_exito is not None


def test_un_mensaje_venenoso_pausa_el_ciclo_y_no_vuelve_a_llamar_al_paso() -> None:
    estado = EstadoComponente("consumo")
    llamadas = 0

    def paso() -> bool:
        nonlocal llamadas
        llamadas += 1
        raise MensajeVenenoso("id-22", "tipo_red: valor no admitido")

    ciclo = iniciar_ciclo(
        paso, "prueba-venenoso", estado, pausa_inactiva=0.01, espera_maxima_error=0.01
    )
    try:
        esperar(lambda: estado.estado is EstadoCiclo.PAUSADO)
        time.sleep(0.2)
        assert llamadas == 1
        resumen = estado.resumen()
        assert resumen["estado"] == "PAUSADO"
        assert resumen["id_mensaje_pausa"] == "id-22"
        assert resumen["motivo_pausa"] == "tipo_red: valor no admitido"
        inicio = time.monotonic()
    finally:
        ciclo.detener()
    assert time.monotonic() - inicio < 1
    assert estado.estado is EstadoCiclo.DETENIDO


def test_detener_durante_la_espera_termina_en_menos_de_un_segundo() -> None:
    estado = EstadoComponente("prueba")
    ciclo = iniciar_ciclo(lambda: False, "prueba-espera", estado, pausa_inactiva=30)
    esperar(lambda: estado.estado is EstadoCiclo.OPERANDO)
    inicio = time.monotonic()
    ciclo.detener()
    assert time.monotonic() - inicio < 1


def test_cerrar_se_llama_una_vez_y_el_hilo_tiene_nombre_y_no_es_daemon() -> None:
    cerrar = Mock()
    estado = EstadoComponente("prueba")
    ciclo = iniciar_ciclo(lambda: False, "ciclo-nombrado", estado, cerrar=cerrar)
    assert ciclo.hilo.name == "ciclo-nombrado"
    assert not ciclo.hilo.daemon
    ciclo.detener()
    ciclo.detener()
    cerrar.assert_called_once_with()
    assert estado.estado is EstadoCiclo.DETENIDO
    assert not ciclo.hilo.is_alive()


def test_detener_con_plazo_vencido_lanza_timeout() -> None:
    liberar = threading.Event()
    en_paso = threading.Event()

    def paso() -> bool:
        en_paso.set()
        liberar.wait(5)
        return False

    ciclo = iniciar_ciclo(paso, "prueba-bloqueada", EstadoComponente("prueba"))
    assert en_paso.wait(1)
    with pytest.raises(TimeoutError):
        ciclo.detener(plazo=0.1)
    liberar.set()
    ciclo.detener()


@pytest.mark.parametrize("opciones", [{"pausa_inactiva": 0}, {"espera_maxima_error": 0}])
def test_parametros_no_positivos_fallan(opciones: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        iniciar_ciclo(lambda: False, "invalido", EstadoComponente("prueba"), **opciones)


def test_el_resumen_del_componente_es_serializable() -> None:
    estado = EstadoComponente("despacho", EstadoCiclo.OPERANDO)
    assert estado.resumen() == {
        "estado": "OPERANDO",
        "ultimo_error": None,
        "id_mensaje_pausa": None,
        "motivo_pausa": None,
        "ultimo_exito": None,
    }
    estado.marcar_operando()
    assert estado.resumen()["ultimo_exito"] is not None
    assert estado.esta_operando()
