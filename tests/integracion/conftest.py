import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from cotizaciones.config.database import Database, create_database
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente

from ..unitarias.dominio.datos import catalogo_laboratorio
from .datos import registrar_catalogo

URL_PREDETERMINADA = (
    "postgresql+psycopg://cotizaciones:cotizaciones_local@127.0.0.1:55436/cotizaciones"
)
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(scope="session")
def base_integracion() -> Iterator[Database]:
    url = make_url(os.getenv("COTIZACIONES_TEST_DATABASE_URL", URL_PREDETERMINADA))
    nombre = "cotizaciones_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin.connect() as conexion:
            conexion.execute(text(f'CREATE DATABASE "{nombre}"'))
    except Exception:
        admin.dispose()
        pytest.fail(
            "PostgreSQL requerido: docker compose up -d --wait postgres "
            "(COTIZACIONES_TEST_DATABASE_URL)",
            pytrace=False,
        )
    base = create_database(
        url.set(database=nombre).render_as_string(hide_password=False),
        pool_size=5,
        max_overflow=5,
        statement_timeout_ms=10_000,
    )
    try:
        configuracion = Config(str(ALEMBIC_INI))
        with base.engine.begin() as conexion:
            configuracion.attributes["connection"] = conexion
            command.upgrade(configuracion, "head")
        yield base
    finally:
        base.close()
        with admin.connect() as conexion:
            conexion.execute(text(f'DROP DATABASE "{nombre}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def base(base_integracion: Database) -> Iterator[Database]:
    from cotizaciones.config.persistencia import metadata

    with base_integracion.engine.begin() as conexion:
        tablas = ", ".join(tabla.fullname for tabla in metadata.sorted_tables)
        conexion.execute(text(f"TRUNCATE {tablas} CASCADE"))
    yield base_integracion


@pytest.fixture
def catalogo_v1(base: Database) -> CatalogoVigente:
    catalogo = catalogo_laboratorio()
    registrar_catalogo(base, catalogo)
    return catalogo
