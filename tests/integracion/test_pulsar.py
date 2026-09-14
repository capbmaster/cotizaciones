import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pulsar
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, update

from cotizaciones.api.app import create_app
from cotizaciones.config.bootstrap import componer_despacho_resultados
from cotizaciones.config.database import Database
from cotizaciones.infraestructura.despacho import iniciar_despacho
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.eventos import (
    CotizacionRechazadaV1,
    CotizacionRegistradaV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
    comando_desde_mensaje,
)
from cotizaciones.modulos.cotizaciones.infraestructura.orm import CotizacionSQL
from cotizaciones.seedwork.infraestructura.ciclos import EstadoCiclo, EstadoComponente
from cotizaciones.seedwork.infraestructura.inbox import EntradaSQL
from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox, SalidaSQL

from ..unitarias.aplicacion.datos import comando_peticion
from ..unitarias.dominio.datos import A101, catalogo_laboratorio, uuid_lab
from .datos import (
    contar,
    marcas_sin_efecto,
    procesar_sql,
    registrar_catalogo,
    salidas_enviadas,
    salidas_pendientes,
)
from .pulsar import URL_ADMIN, LaboratorioPulsar, esperar, peticion_nueva

RAIZ = Path(__file__).resolve().parents[2]
F5 = {
    "command_id": str(uuid_lab("0042")),
    "id_peticion": str(uuid_lab("0041")),
    "id_trabajo": str(uuid_lab("0040")),
    "categoria": "jardineria",
}
REGISTRADA_ORQUESTACION = "orquestacion-cotizacion-registrada-v1"
REGISTRADA_SEGUIMIENTO = "seguimiento-cotizacion-registrada"
RECHAZADA_ORQUESTACION = "orquestacion-cotizacion-rechazada-v1"
RECHAZADA_SEGUIMIENTO = "seguimiento-cotizacion-rechazada-v1"


def componente(aplicacion: FastAPI, nombre: str) -> dict[str, str | None]:
    estado = aplicacion.state.estado_mensajeria
    return estado.resumen()[nombre] if estado is not None else {}


def vencer_reservas(base: Database) -> None:
    with base.engine.begin() as conexion:
        conexion.execute(
            update(SalidaSQL).values(
                vence_en=func.clock_timestamp() - timedelta(seconds=1),
                proximo_intento=func.clock_timestamp(),
            )
        )


def lector_v1(
    laboratorio: LaboratorioPulsar, suscripcion: str, solo: str, base_sqlite: Path, limite: int
) -> subprocess.CompletedProcess[str]:
    configuracion = laboratorio.configuracion
    return subprocess.run(
        [
            sys.executable,
            str(RAIZ / "scripts" / "consumir_resultados.py"),
            "--url",
            configuracion.pulsar_url,
            "--topico-registrada",
            configuracion.topico_registrada,
            "--topico-rechazada",
            configuracion.topico_rechazada,
            "--solo",
            solo,
            "--suscripcion",
            suscripcion,
            "--base",
            str(base_sqlite),
            "--limite",
            str(limite),
            "--timeout-ms",
            "15000",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def filas_sqlite(archivo: Path) -> int:
    with sqlite3.connect(archivo) as conexion:
        return int(conexion.execute("SELECT count(*) FROM recibidos").fetchone()[0])


def recibir_todos(consumidor: Any, espera_ms: int = 1500) -> list[Any]:
    recibidos: list[Any] = []
    while True:
        try:
            mensaje = consumidor.receive(timeout_millis=espera_ms)
        except pulsar.Timeout:
            return recibidos
        consumidor.acknowledge(mensaje)
        recibidos.append(mensaje)


def test_un_comando_real_del_doble_produce_fila_salida_y_resultado_decodificable(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar, tmp_path: Path
) -> None:
    configuracion = laboratorio.configuracion
    orquestacion = laboratorio.suscribir(
        configuracion.topico_registrada, REGISTRADA_ORQUESTACION, CotizacionRegistradaV1
    )
    laboratorio.preparar_suscripcion_servicio()
    salida = tmp_path / "enviados.jsonl"
    doble = subprocess.run(
        [
            sys.executable,
            str(RAIZ / "scripts" / "enviar_peticion.py"),
            "--url",
            configuracion.pulsar_url,
            "--topico",
            configuracion.topico_peticiones,
            "--salida",
            str(salida),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert doble.returncode == 0, doble.stderr
    assert "DOBLE DE ORQUESTACION" in doble.stdout
    enviado = json.loads(salida.read_text(encoding="utf-8").splitlines()[0])
    with TestClient(create_app(configuracion)):
        esperar(lambda: salidas_enviadas(base) == 1)
    mensaje = orquestacion.receive(timeout_millis=10000)
    valor = mensaje.value()
    orquestacion.acknowledge(mensaje)
    assert valor.tipo == "CotizacionRegistrada.v1"
    assert valor.causacion == enviado["command_id"]
    assert valor.id_peticion == enviado["id_peticion"]
    assert valor.id_proveedor == str(A101)
    assert valor.importe_menor == 15_000_000
    assert mensaje.properties() == {"event_id": valor.event_id, "tipo": valor.tipo}
    assert mensaje.partition_key() == enviado["id_trabajo"]
    assert (contar(base, CotizacionSQL), contar(base, EntradaSQL)) == (1, 1)


def test_cada_resultado_llega_una_vez_a_su_topico_y_a_dos_suscripciones(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar, tmp_path: Path
) -> None:
    configuracion = laboratorio.configuracion
    entorno = {
        **os.environ,
        "COTIZACIONES_PULSAR_URL": configuracion.pulsar_url,
        "COTIZACIONES_TOPICO_PETICIONES": configuracion.topico_peticiones,
        "COTIZACIONES_TOPICO_REGISTRADA": configuracion.topico_registrada,
        "COTIZACIONES_TOPICO_RECHAZADA": configuracion.topico_rechazada,
    }
    preparacion = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "preparar_pulsar.py"), "--admin-url", URL_ADMIN],
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert preparacion.returncode == 0, preparacion.stderr
    assert f"Suscripcion disponible: {REGISTRADA_SEGUIMIENTO}" in preparacion.stdout
    politicas = [json.loads(linea) for linea in preparacion.stdout.splitlines() if linea[:1] == "{"]
    assert len(politicas) == 3
    assert all(p["retencion"]["retentionTimeInMinutes"] == 60 for p in politicas)
    laboratorio.enviar()
    laboratorio.enviar(**F5)
    with TestClient(create_app(configuracion)):
        esperar(lambda: salidas_enviadas(base) == 2)

    base_orquestacion = tmp_path / "orquestacion.db"
    for suscripcion, solo in (
        (REGISTRADA_ORQUESTACION, "registrada"),
        (RECHAZADA_ORQUESTACION, "rechazada"),
    ):
        lectura = lector_v1(laboratorio, suscripcion, solo, base_orquestacion, limite=1)
        assert lectura.returncode == 0, lectura.stderr
    assert filas_sqlite(base_orquestacion) == 2

    for topico, suscripcion, record, tipo in (
        (
            configuracion.topico_registrada,
            REGISTRADA_SEGUIMIENTO,
            CotizacionRegistradaV1,
            "CotizacionRegistrada.v1",
        ),
        (
            configuracion.topico_rechazada,
            RECHAZADA_SEGUIMIENTO,
            CotizacionRechazadaV1,
            "CotizacionRechazada.v1",
        ),
    ):
        consumidor = laboratorio.suscribir(topico, suscripcion, record)
        recibidos = recibir_todos(consumidor)
        consumidor.close()
        assert [m.value().tipo for m in recibidos] == [tipo]


def test_caida_despues_del_commit_y_antes_del_ack_converge_al_reiniciar(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    configuracion = laboratorio.configuracion
    laboratorio.preparar_suscripcion_servicio()
    laboratorio.enviar()
    consumidor = laboratorio.suscribir(
        configuracion.topico_peticiones, configuracion.suscripcion_peticiones, SolicitarCotizacionV1
    )
    mensaje = consumidor.receive(timeout_millis=10000)
    assert procesar_sql(base)(comando_desde_mensaje(mensaje.value())).nueva is True
    consumidor.close()  # commit hecho y sin ACK: el proceso "cae" aquí
    assert laboratorio.backlog_servicio() == 1
    with TestClient(create_app(configuracion)):
        esperar(lambda: laboratorio.backlog_servicio() == 0 and salidas_enviadas(base) == 1)
    assert (contar(base, CotizacionSQL), contar(base, EntradaSQL), contar(base, SalidaSQL)) == (
        1,
        1,
        1,
    )


def test_caida_tras_el_envio_y_antes_de_marcar_republica_el_mismo_event_id(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar, tmp_path: Path
) -> None:
    configuracion = laboratorio.configuracion
    laboratorio.suscribir(
        configuracion.topico_registrada, REGISTRADA_ORQUESTACION, CotizacionRegistradaV1
    ).close()
    procesar_sql(base)(comando_peticion())
    despachador, cerrar = componer_despacho_resultados(base, configuracion)
    try:
        with patch.object(despachador.outbox, "confirmar", side_effect=RuntimeError("caida")):
            with pytest.raises(RuntimeError, match="caida"):
                despachador.despachar_lote()
        assert salidas_pendientes(base) == 1
        vencer_reservas(base)
        assert despachador.despachar_lote() == 1
    finally:
        cerrar()
    lectura = lector_v1(
        laboratorio, REGISTRADA_ORQUESTACION, "registrada", tmp_path / "lector.db", limite=2
    )
    assert lectura.returncode == 0, lectura.stderr
    lineas = [json.loads(linea) for linea in lectura.stdout.splitlines() if linea[:1] == "{"]
    assert [linea["persistido"] for linea in lineas] == [True, False]
    assert lineas[0]["event_id"] == lineas[1]["event_id"]
    assert filas_sqlite(tmp_path / "lector.db") == 1


def test_broker_inaccesible_deja_la_salida_pendiente_y_luego_se_publica(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    configuracion = laboratorio.configuracion
    procesar_sql(base)(comando_peticion())
    inaccesible = replace(configuracion, pulsar_url="pulsar://127.0.0.1:1")
    despachador, cerrar = componer_despacho_resultados(base, inaccesible)
    estado = EstadoComponente("despacho-resultados")
    ciclo = iniciar_despacho(despachador, estado, cerrar=cerrar)
    try:
        esperar(lambda: estado.estado is EstadoCiclo.REINTENTANDO, segundos=30)
    finally:
        ciclo.detener()
    assert contar(base, CotizacionSQL) == 1
    assert salidas_pendientes(base) == 1
    (pendiente,) = RepositorioOutbox(base.session_factory).inspeccionar()
    assert pendiente["ultimo_error"]
    assert estado.ultimo_error is not None and "ErrorPublicacion" in estado.ultimo_error
    vencer_reservas(base)
    correcto, cerrar_correcto = componer_despacho_resultados(base, configuracion)
    try:
        assert correcto.despachar_lote() == 1
    finally:
        cerrar_correcto()
    assert salidas_enviadas(base) == 1


def test_catalogo_ausente_hace_nack_sin_fila_y_se_procesa_al_cargarlo(
    base: Database, laboratorio: LaboratorioPulsar
) -> None:
    laboratorio.preparar_suscripcion_servicio()
    laboratorio.enviar()
    aplicacion = create_app(laboratorio.configuracion)
    with TestClient(aplicacion):
        esperar(lambda: componente(aplicacion, "consumo-peticiones")["estado"] == "REINTENTANDO")
        assert "CatalogoNoDisponible" in str(
            componente(aplicacion, "consumo-peticiones")["ultimo_error"]
        )
        assert (contar(base, CotizacionSQL), contar(base, EntradaSQL)) == (0, 0)
        registrar_catalogo(base, catalogo_laboratorio())
        esperar(lambda: salidas_enviadas(base) == 1, segundos=30)
        esperar(lambda: componente(aplicacion, "consumo-peticiones")["estado"] == "OPERANDO")
    assert laboratorio.backlog_servicio() == 0


def test_mensaje_invalido_pausa_el_consumo_y_el_despacho_sigue_operando(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    laboratorio.preparar_suscripcion_servicio()
    invalido = laboratorio.enviar(**peticion_nueva(tipo_red="OTRA_RED"))
    aplicacion = create_app(laboratorio.configuracion)
    with TestClient(aplicacion) as cliente:
        esperar(lambda: componente(aplicacion, "consumo-peticiones")["estado"] == "PAUSADO")
        respuesta = cliente.get("/health/ready")
        assert respuesta.status_code == 503
        cuerpo = respuesta.json()
        assert cuerpo["motivo"] == "mensajeria_no_operativa"
        consumo = cuerpo["componentes"]["consumo-peticiones"]
        assert consumo["id_mensaje_pausa"] == invalido["command_id"]
        assert "tipo_red" in consumo["motivo_pausa"]
        procesar_sql(base)(comando_peticion())
        esperar(lambda: salidas_enviadas(base) == 1)
        assert componente(aplicacion, "despacho-resultados")["estado"] == "OPERANDO"
        assert cliente.get("/health/live").status_code == 200
    assert laboratorio.backlog_servicio() == 1  # el mensaje inválido se conserva sin ACK


def test_con_cotizaciones_detenido_el_productor_sigue_y_el_backlog_crece(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    laboratorio.preparar_suscripcion_servicio()
    enviados = [laboratorio.enviar(**peticion_nueva()) for _ in range(5)]
    esperar(lambda: laboratorio.backlog_servicio() == 5)
    assert contar(base, CotizacionSQL) == 0
    with TestClient(create_app(laboratorio.configuracion)):
        esperar(lambda: laboratorio.backlog_servicio() == 0 and salidas_enviadas(base) == 5)
    assert contar(base, CotizacionSQL) == len(enviados)
    assert marcas_sin_efecto(base) == 0
