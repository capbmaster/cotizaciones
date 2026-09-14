import threading
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cotizaciones.api.app import create_app
from cotizaciones.config import bootstrap
from cotizaciones.config.database import Database
from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ResultadoProcesamiento,
)
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente
from cotizaciones.modulos.cotizaciones.infraestructura.orm import CotizacionSQL
from cotizaciones.seedwork.infraestructura.inbox import EntradaSQL
from cotizaciones.seedwork.infraestructura.outbox import SalidaSQL
from cotizaciones.seedwork.infraestructura.unidad_trabajo_sqlalchemy import UnidadTrabajoSQL

from .datos import contar, marcas_sin_efecto, salidas_enviadas
from .pulsar import LaboratorioPulsar, esperar, peticion_nueva

NOMBRES = ("consumo-peticiones", "despacho-resultados")


class CaidaSimulada(BaseException):
    """No la atrapa `except Exception`: el hilo muere como en una caída del proceso."""


def hilos_de_mensajeria() -> list[str]:
    return sorted(hilo.name for hilo in threading.enumerate() if hilo.name in NOMBRES)


def componente(aplicacion: FastAPI, nombre: str) -> dict[str, str | None]:
    estado = aplicacion.state.estado_mensajeria
    return estado.resumen()[nombre] if estado is not None else {}


def test_iniciar_y_cerrar_dos_veces_no_deja_hilos_duplicados_ni_vivos(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    aplicacion = create_app(laboratorio.configuracion)
    for _ in range(2):
        with TestClient(aplicacion):
            esperar(lambda: hilos_de_mensajeria() == sorted(NOMBRES))
        assert hilos_de_mensajeria() == []


def test_los_mensajes_se_procesan_sin_ninguna_peticion_http(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    laboratorio.preparar_suscripcion_servicio()
    with TestClient(create_app(laboratorio.configuracion)):
        laboratorio.enviar()
        esperar(lambda: salidas_enviadas(base) == 1)
    assert contar(base, CotizacionSQL) == 1


def test_live_responde_mientras_el_consumidor_espera_en_receive(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    aplicacion = create_app(laboratorio.configuracion)
    with TestClient(aplicacion) as cliente:
        esperar(lambda: componente(aplicacion, "consumo-peticiones")["estado"] == "OPERANDO")
        for _ in range(3):
            inicio = time.monotonic()
            assert cliente.get("/health/live").status_code == 200
            assert time.monotonic() - inicio < 0.5
        listo = cliente.get("/health/ready")
        assert listo.status_code == 200, listo.json()


def test_la_parada_durante_la_espera_termina_en_menos_de_10_s(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    aplicacion = create_app(laboratorio.configuracion)
    cliente = TestClient(aplicacion)
    cliente.__enter__()
    esperar(lambda: componente(aplicacion, "consumo-peticiones")["estado"] == "OPERANDO")
    inicio = time.monotonic()
    cliente.__exit__(None, None, None)
    assert time.monotonic() - inicio < 10
    assert hilos_de_mensajeria() == []


def test_la_parada_durante_una_transaccion_nunca_hace_ack_sin_commit(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    laboratorio.preparar_suscripcion_servicio()
    en_confirmacion = threading.Event()
    original = UnidadTrabajoSQL.confirmar

    def confirmar_lento(unidad: UnidadTrabajoSQL) -> None:
        en_confirmacion.set()
        time.sleep(1.5)
        original(unidad)

    with patch.object(UnidadTrabajoSQL, "confirmar", confirmar_lento):
        cliente = TestClient(create_app(laboratorio.configuracion))
        cliente.__enter__()
        laboratorio.enviar()
        assert en_confirmacion.wait(20)
        inicio = time.monotonic()
        cliente.__exit__(None, None, None)
        duracion = time.monotonic() - inicio
    assert duracion < 10
    # El cierre esperó el paso en curso: commit primero, ACK después.
    assert contar(base, CotizacionSQL) == 1
    esperar(lambda: laboratorio.backlog_servicio() == 0)


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_reiniciar_despues_de_un_commit_sin_ack_converge(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    laboratorio.preparar_suscripcion_servicio()
    real = bootstrap.componer_procesamiento_sql

    def con_caida(
        base_datos: Database,
    ) -> Callable[[ProcesarPeticionCotizacion], ResultadoProcesamiento]:
        manejador = real(base_datos)

        def procesar(comando: ProcesarPeticionCotizacion) -> ResultadoProcesamiento:
            manejador(comando)
            raise CaidaSimulada("caida tras el commit y antes del ACK")

        return procesar

    with patch.object(bootstrap, "componer_procesamiento_sql", con_caida):
        aplicacion = create_app(laboratorio.configuracion)
        with TestClient(aplicacion):
            laboratorio.enviar()
            esperar(lambda: contar(base, CotizacionSQL) == 1)
            esperar(lambda: componente(aplicacion, "consumo-peticiones")["estado"] == "DETENIDO")
    assert laboratorio.backlog_servicio() == 1
    with TestClient(create_app(laboratorio.configuracion)):
        esperar(lambda: laboratorio.backlog_servicio() == 0 and salidas_enviadas(base) == 1)
    assert (contar(base, CotizacionSQL), contar(base, EntradaSQL), contar(base, SalidaSQL)) == (
        1,
        1,
        1,
    )


def test_dos_instancias_con_la_misma_base_y_suscripcion_no_duplican(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    laboratorio.preparar_suscripcion_servicio()
    enviados: list[dict[str, Any]] = [laboratorio.enviar(**peticion_nueva()) for _ in range(20)]
    with (
        TestClient(create_app(laboratorio.configuracion)),
        TestClient(create_app(laboratorio.configuracion)),
    ):
        esperar(
            lambda: contar(base, CotizacionSQL) == 20 and salidas_enviadas(base) == 20,
            segundos=60,
        )
    assert contar(base, EntradaSQL) == len(enviados)
    assert marcas_sin_efecto(base) == 0
    esperar(lambda: laboratorio.backlog_servicio() == 0)
