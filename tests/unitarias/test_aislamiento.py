import json
import os
import subprocess
import sys

# Cada fase añade aquí los módulos de dominio, aplicación y persistencia que cree.
MODULOS_SIN_MENSAJERIA = (
    "cotizaciones.api.app",
    "cotizaciones.config.settings",
    "cotizaciones.config.database",
)
PROHIBIDOS = ("pulsar", "solicitudes_partner")

# Dominio puro: además de Pulsar y Entrada, tampoco puede cargar SQL ni HTTP.
MODULOS_DOMINIO = (
    "cotizaciones.seedwork.dominio.entidades",
    "cotizaciones.seedwork.dominio.eventos",
    "cotizaciones.seedwork.dominio.objetos_valor",
    "cotizaciones.seedwork.dominio.validaciones",
    "cotizaciones.modulos.cotizaciones.dominio.entidades",
    "cotizaciones.modulos.cotizaciones.dominio.eventos",
    "cotizaciones.modulos.cotizaciones.dominio.excepciones",
    "cotizaciones.modulos.cotizaciones.dominio.objetos_valor",
    "cotizaciones.modulos.cotizaciones.dominio.repositorios",
    "cotizaciones.modulos.cotizaciones.dominio.servicios",
)
PROHIBIDOS_DOMINIO = ("sqlalchemy", "psycopg", "pulsar", "fastapi", "solicitudes_partner")

_CARGAR_Y_LISTAR = """
import importlib
import json
import sys

modulos, prohibidos = json.loads(sys.argv[1]), json.loads(sys.argv[2])
for modulo in modulos:
    importlib.import_module(modulo)
cargados = sorted(
    nombre
    for nombre in sys.modules
    if any(nombre == p or nombre.startswith(p + ".") for p in prohibidos)
)
print(json.dumps(cargados))
"""

_SIN_CONEXIONES = """
import socket
from unittest.mock import patch

import psycopg

def conexion_prohibida(*args, **kwargs):
    raise AssertionError("Conexion externa inesperada")

with (
    patch.object(socket.socket, "connect", conexion_prohibida),
    patch.object(socket.socket, "connect_ex", conexion_prohibida),
    patch.object(socket, "create_connection", conexion_prohibida),
    patch.object(psycopg, "connect", conexion_prohibida),
):
    from fastapi.testclient import TestClient
    from cotizaciones.api.app import create_app
    with TestClient(create_app()) as cliente:
        assert cliente.get("/health/live").status_code == 200
        assert cliente.get("/health/ready").json()["motivo"] == "base_no_configurada"
"""


def _entorno_sin_configuracion() -> dict[str, str]:
    return {
        nombre: valor
        for nombre, valor in os.environ.items()
        if not nombre.startswith(("COTIZACIONES_", "PULSAR_", "PG")) and nombre != "DATABASE_URL"
    }


def _prohibidos_cargados(modulos: tuple[str, ...], prohibidos: tuple[str, ...]) -> list[str]:
    resultado = subprocess.run(
        [sys.executable, "-I", "-c", _CARGAR_Y_LISTAR, json.dumps(modulos), json.dumps(prohibidos)],
        env=_entorno_sin_configuracion(),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    cargados: list[str] = json.loads(resultado.stdout)
    return cargados


def test_importar_la_base_no_carga_pulsar_ni_entrada() -> None:
    assert _prohibidos_cargados(MODULOS_SIN_MENSAJERIA, PROHIBIDOS) == []


def test_dominio_no_carga_sql_http_mensajeria_ni_entrada() -> None:
    assert _prohibidos_cargados(MODULOS_DOMINIO, PROHIBIDOS_DOMINIO) == []


def test_la_verificacion_detecta_un_import_prohibido() -> None:
    assert "pulsar" in _prohibidos_cargados(("pulsar",), PROHIBIDOS)


def test_import_y_lifespan_sin_base_no_abren_conexiones() -> None:
    resultado = subprocess.run(
        [sys.executable, "-I", "-c", _SIN_CONEXIONES],
        env=_entorno_sin_configuracion(),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
