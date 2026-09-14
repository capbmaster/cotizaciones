from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.pool import QueuePool

from cotizaciones.config.database import Database
from cotizaciones.config.persistencia import verificar_destinos
from cotizaciones.config.rutas import DESTINO_REGISTRADA
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import decodificar_evento
from cotizaciones.seedwork.aplicacion.publicacion import Publicacion
from cotizaciones.seedwork.infraestructura.despacho_outbox import DespachadorOutbox
from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox, SalidaSQL

from .datos import evento_resuelto, registrar_salidas


class Transporte:
    def __init__(self, confirmar: bool = True) -> None:
        self.confirmar = confirmar
        self.publicaciones: list[Publicacion] = []

    def publicar(self, publicacion: Publicacion) -> bool:
        self.publicaciones.append(publicacion)
        return self.confirmar


def vencer_reservas(base: Database) -> None:
    with base.engine.begin() as conexion:
        conexion.execute(
            update(SalidaSQL).values(vence_en=func.clock_timestamp() - timedelta(seconds=1))
        )


def test_la_salida_de_un_resultado_va_a_su_destino(base: Database) -> None:
    evento = evento_resuelto()
    registrar_salidas(base, [evento])
    (reserva,) = RepositorioOutbox(base.session_factory).reclamar("A", 5, timedelta(seconds=30))
    assert reserva.publicacion.destino == DESTINO_REGISTRADA
    assert reserva.publicacion.id_evento == evento.id_evento
    assert decodificar_evento(reserva.publicacion.documento) == evento


def test_reserva_vencida_no_se_confirma_con_el_token_anterior(base: Database) -> None:
    registrar_salidas(base, [evento_resuelto()])
    outbox = RepositorioOutbox(base.session_factory)
    primera = outbox.reclamar("A", 1, timedelta(seconds=30))[0]
    assert outbox.reclamar("B", 1, timedelta(seconds=30)) == []
    vencer_reservas(base)
    segunda = outbox.reclamar("B", 1, timedelta(seconds=30))[0]
    assert primera.id == segunda.id and primera.token != segunda.token
    assert not outbox.confirmar(primera)
    assert not outbox.reprogramar(primera, "tarde", timedelta(seconds=1))
    assert outbox.confirmar(segunda)
    assert outbox.reclamar("C", 1, timedelta(seconds=30)) == []
    with base.session_factory() as sesion:
        fila = sesion.scalar(select(SalidaSQL))
        assert fila is not None and fila.intentos == 2 and fila.enviada_en is not None


def test_dos_despachadores_no_reservan_la_misma_fila(base: Database) -> None:
    base_evento = evento_resuelto()
    registrar_salidas(base, [replace(base_evento, id_evento=uuid4()) for _ in range(10)])
    barrera = Barrier(2)
    outbox = RepositorioOutbox(base.session_factory)

    def reclamar(propietario: str) -> set[UUID]:
        barrera.wait(timeout=5)
        return {reserva.id for reserva in outbox.reclamar(propietario, 5, timedelta(seconds=30))}

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        primera, segunda = list(ejecutor.map(reclamar, ["A", "B"]))
    assert len(primera | segunda) == 10 and not primera & segunda


def test_reintento_publica_el_mismo_id_evento_y_documento(base: Database) -> None:
    evento = evento_resuelto()
    registrar_salidas(base, [evento])
    transporte = Transporte(confirmar=False)
    outbox = RepositorioOutbox(base.session_factory)
    despacho = DespachadorOutbox(outbox, transporte, "prueba", demora_reintento=timedelta(0))
    assert despacho.despachar_lote() == 0
    assert outbox.metricas()["pendientes"] == 1
    assert outbox.inspeccionar()[0]["ultimo_error"] == "Publicacion sin acuse positivo"
    transporte.confirmar = True
    assert despacho.despachar_lote() == 1
    primera, segunda = transporte.publicaciones
    assert primera == segunda
    assert primera.id_evento == evento.id_evento
    assert decodificar_evento(primera.documento) == evento
    assert outbox.metricas()["pendientes"] == 0


def test_despachar_lote_respeta_el_limite_y_devuelve_las_confirmadas(base: Database) -> None:
    base_evento = evento_resuelto()
    registrar_salidas(base, [replace(base_evento, id_evento=uuid4()) for _ in range(3)])
    despacho = DespachadorOutbox(RepositorioOutbox(base.session_factory), Transporte(), "A")
    assert despacho.despachar_lote(2) == 2
    assert despacho.despachar_lote(2) == 1
    assert despacho.despachar_lote(2) == 0


def test_la_publicacion_ocurre_sin_transaccion_sql_abierta(base: Database) -> None:
    registrar_salidas(base, [evento_resuelto()])

    class TransporteVigilante(Transporte):
        def publicar(self, publicacion: Publicacion) -> bool:
            assert isinstance(base.engine.pool, QueuePool)
            assert base.engine.pool.checkedout() == 0
            return super().publicar(publicacion)

    despacho = DespachadorOutbox(
        RepositorioOutbox(base.session_factory), TransporteVigilante(), "A"
    )
    assert despacho.despachar_lote() == 1


def test_caida_despues_de_enviar_y_antes_de_marcar_republica_lo_mismo(base: Database) -> None:
    registrar_salidas(base, [evento_resuelto()])
    transporte = Transporte()
    outbox = RepositorioOutbox(base.session_factory)
    despacho = DespachadorOutbox(outbox, transporte, "A")
    with patch.object(outbox, "confirmar", side_effect=RuntimeError("Caida")):
        with pytest.raises(RuntimeError, match="Caida"):
            despacho.despachar_lote()
    assert outbox.metricas()["pendientes"] == 1
    vencer_reservas(base)
    base.engine.dispose()
    assert despacho.despachar_lote() == 1
    primera, segunda = transporte.publicaciones
    assert primera == segunda


def test_destinos_independientes_y_reintento_conserva_identidad(base: Database) -> None:
    registrar_salidas(base, [evento_resuelto()], destinos=("destino.uno", "destino.dos"))
    outbox = RepositorioOutbox(base.session_factory)
    reservas = outbox.reclamar("A", 2, timedelta(seconds=30))
    assert len({reserva.id for reserva in reservas}) == 2
    assert len({reserva.publicacion.id_evento for reserva in reservas}) == 1
    assert outbox.confirmar(reservas[0])
    assert outbox.reprogramar(reservas[1], "broker no disponible", timedelta(0))
    repetida = outbox.reclamar("B", 2, timedelta(seconds=30))
    assert len(repetida) == 1
    assert repetida[0].publicacion == reservas[1].publicacion
    assert outbox.inspeccionar()[0]["ultimo_error"] == "broker no disponible"


def test_destinos_desconocidos_solo_bloquean_mientras_estan_pendientes(base: Database) -> None:
    registrar_salidas(base, [evento_resuelto()])
    verificar_destinos(base)
    with base.engine.begin() as conexion:
        conexion.execute(update(SalidaSQL).values(destino="laboratorio.anterior"))
    with pytest.raises(ValueError, match="destinos pendientes desconocidos"):
        verificar_destinos(base)
    with base.engine.begin() as conexion:
        conexion.execute(update(SalidaSQL).values(enviada_en=func.clock_timestamp()))
    verificar_destinos(base)
