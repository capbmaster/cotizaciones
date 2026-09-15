from unittest.mock import Mock

import psycopg
import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from cotizaciones.config.database import Database, create_database

URL_PUERTO_CERRADO = "postgresql+psycopg://prueba:prueba@127.0.0.1:1/prueba"


def _crear(url: str = URL_PUERTO_CERRADO, **limites: int) -> Database:
    parametros = {"pool_size": 3, "max_overflow": 2, "statement_timeout_ms": 1234}
    parametros.update(limites)
    return create_database(url, **parametros)


@pytest.mark.parametrize(
    "url", ["sqlite://", "postgresql://prueba", "postgresql+psycopg2://prueba"]
)
def test_exige_driver_postgresql_psycopg(url: str) -> None:
    with pytest.raises(ValueError, match="postgresql\\+psycopg"):
        _crear(url)


def test_crear_no_conecta_y_entrega_sesiones_independientes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conexion = Mock(side_effect=AssertionError("conexion inesperada"))
    monkeypatch.setattr(psycopg, "connect", conexion)
    base = _crear()
    try:
        with base.session_factory() as primera, base.session_factory() as segunda:
            assert primera is not segunda
            assert primera.bind is base.engine
            assert segunda.bind is base.engine
    finally:
        base.close()
    conexion.assert_not_called()


def test_aplica_limites_del_pool_y_pre_ping() -> None:
    base = _crear(pool_size=3, max_overflow=2)
    try:
        pool = base.engine.pool
        assert isinstance(pool, QueuePool)
        assert pool.size() == 3
        assert pool._max_overflow == 2
        assert pool._pre_ping is True
    finally:
        base.close()


def test_statement_timeout_viaja_como_opcion_de_conexion(monkeypatch: pytest.MonkeyPatch) -> None:
    conexion = Mock(side_effect=psycopg.OperationalError("sin red en prueba unitaria"))
    monkeypatch.setattr(psycopg, "connect", conexion)
    base = _crear(statement_timeout_ms=1234)
    try:
        assert base.verificar() is False
    finally:
        base.close()
    conexion.assert_called()
    opciones = conexion.call_args.kwargs["options"]
    assert "-c statement_timeout=1234" in opciones
    assert "-c search_path=public" in opciones


def test_verificar_con_puerto_cerrado_devuelve_falso_sin_propagar() -> None:
    base = _crear(URL_PUERTO_CERRADO)
    try:
        assert base.verificar() is False
    finally:
        base.close()


def test_close_libera_el_engine() -> None:
    engine = Mock(spec=Engine)
    Database(engine=engine, session_factory=sessionmaker()).close()
    engine.dispose.assert_called_once_with()


def test_close_se_puede_llamar_dos_veces() -> None:
    base = _crear()
    base.close()
    base.close()


def test_connection_and_pool_waits_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = Mock(side_effect=psycopg.OperationalError("offline"))
    monkeypatch.setattr(psycopg, "connect", connect)
    database = _crear()
    try:
        assert not database.verificar()
        assert connect.call_args.kwargs["connect_timeout"] == 3
        assert isinstance(database.engine.pool, QueuePool)
        assert database.engine.pool.timeout() == 2
    finally:
        database.close()
