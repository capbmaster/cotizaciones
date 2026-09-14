from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from cotizaciones.config.database import Database
from cotizaciones.config.persistencia import metadata
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
ESQUEMAS = {"cotizaciones", "mensajeria"}
RESTRICCIONES = {
    "ck_catalogo_version",
    "ck_oferta_tipo_red",
    "ck_oferta_importe",
    "ck_oferta_moneda",
    "ck_oferta_red_partner",
    "uq_oferta_catalogo",
    "fk_oferta_catalogo",
    "uq_cotizacion_peticion",
    "ck_cotizacion_version",
    "ck_cotizacion_estado",
    "ck_cotizacion_motivo",
    "ck_cotizacion_resultado",
    "fk_cotizacion_catalogo",
    "uq_salida_destino",
    "ck_oferta_duracion",
    "ck_cotizacion_duracion",
}
INDICES = {
    "uq_catalogo_activo",
    "ix_oferta_version_categoria",
    "ix_cotizacion_trabajo",
    "ix_cotizacion_resuelta",
    "ix_salida_pendiente",
}


def migrar(base: Database, accion: Callable[[Config, str], None], destino: str) -> None:
    configuracion = Config(str(ALEMBIC_INI))
    with base.engine.begin() as conexion:
        configuracion.attributes["connection"] = conexion
        accion(configuracion, destino)


def diferencias_con_orm(base: Database) -> list[object]:
    with base.engine.connect() as conexion:
        contexto = MigrationContext.configure(conexion, opts={"include_schemas": True})
        return list(compare_metadata(contexto, metadata))


def test_migracion_crea_esquemas_y_coincide_con_el_orm(base: Database) -> None:
    assert ESQUEMAS <= set(inspect(base.engine).get_schema_names())
    with base.engine.connect() as conexion:
        assert conexion.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
    assert diferencias_con_orm(base) == []


def test_restricciones_e_indices_con_nombre(base: Database) -> None:
    with base.engine.connect() as conexion:
        restricciones = set(
            conexion.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE connamespace::regnamespace::text IN ('cotizaciones', 'mensajeria')"
                )
            )
        )
        indices = set(
            conexion.scalars(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname IN ('cotizaciones', 'mensajeria')"
                )
            )
        )
        nulos_iguales = conexion.scalar(
            text(
                "SELECT i.indnullsnotdistinct FROM pg_index i "
                "JOIN pg_class x ON x.oid = i.indexrelid WHERE x.relname = 'uq_oferta_catalogo'"
            )
        )
    assert RESTRICCIONES <= restricciones
    assert INDICES <= indices
    assert nulos_iguales is True


OFERTA = (
    "INSERT INTO cotizaciones.ofertas_catalogo "
    "(id, version_catalogo, id_proveedor, categoria, tipo_red, id_partner, importe_menor, moneda, "
    "duracion_estimada_minutos) "
    "VALUES (gen_random_uuid(), 1, {proveedor}, 'plomeria', {red}, {partner}, {importe}, {moneda}, "
    "{duracion})"
)
COTIZACION = (
    "INSERT INTO cotizaciones.cotizaciones (id, id_peticion, id_trabajo, id_solicitud, "
    "id_partner, peticion, id_comando_origen, correlacion, causacion, instante_comando, "
    "version_catalogo, version_cotizacion, estado, id_proveedor, importe_menor, moneda, motivo, "
    "duracion_estimada_minutos, resuelta_en) VALUES (gen_random_uuid(), gen_random_uuid(), "
    "gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), '{{}}'::jsonb, gen_random_uuid(), "
    "gen_random_uuid(), gen_random_uuid(), now(), {version_catalogo}, {version}, {estado}, "
    "{proveedor}, {importe}, {moneda}, {motivo}, {duracion}, now())"
)
A101 = "'00000000-0000-0000-0000-00000000a101'"


def oferta_sql(
    proveedor: str = "gen_random_uuid()",
    red: str = "'GENERAL_HDA'",
    partner: str = "NULL",
    importe: str = "1",
    moneda: str = "'COP'",
    duracion: str = "NULL",
) -> str:
    return OFERTA.format(
        proveedor=proveedor,
        red=red,
        partner=partner,
        importe=importe,
        moneda=moneda,
        duracion=duracion,
    )


def cotizacion_sql(
    estado: str = "'PROPUESTA'",
    proveedor: str = "gen_random_uuid()",
    importe: str = "1",
    moneda: str = "'COP'",
    motivo: str = "NULL",
    version: str = "1",
    version_catalogo: str = "1",
    duracion: str = "NULL",
) -> str:
    return COTIZACION.format(
        estado=estado,
        proveedor=proveedor,
        importe=importe,
        moneda=moneda,
        motivo=motivo,
        version=version,
        version_catalogo=version_catalogo,
        duracion=duracion,
    )


@pytest.mark.parametrize(
    ("restriccion", "sentencia"),
    [
        ("ck_oferta_red_partner", oferta_sql(partner="gen_random_uuid()")),
        ("ck_oferta_red_partner", oferta_sql(red="'HOMOLOGADA_PARTNER'")),
        ("ck_oferta_tipo_red", oferta_sql(red="'OTRA_RED'")),
        ("ck_oferta_importe", oferta_sql(importe="0")),
        ("ck_oferta_moneda", oferta_sql(moneda="'cop'")),
        ("uq_oferta_catalogo", oferta_sql(proveedor=A101)),
        (
            "uq_catalogo_activo",
            "INSERT INTO cotizaciones.catalogos (version, huella, activo) VALUES (2, 'x', true)",
        ),
        (
            "ck_catalogo_version",
            "INSERT INTO cotizaciones.catalogos (version, huella) VALUES (0, 'x')",
        ),
        ("ck_cotizacion_resultado", cotizacion_sql(proveedor="NULL")),
        ("ck_cotizacion_resultado", cotizacion_sql(importe="0")),
        (
            "ck_cotizacion_resultado",
            cotizacion_sql(estado="'RECHAZADA'", motivo="'SIN_PROVEEDOR_EN_RED'"),
        ),
        (
            "ck_cotizacion_motivo",
            cotizacion_sql(
                estado="'RECHAZADA'", proveedor="NULL", importe="NULL", moneda="NULL", motivo="'X'"
            ),
        ),
        ("ck_cotizacion_estado", cotizacion_sql(estado="'PENDIENTE'")),
        ("ck_cotizacion_version", cotizacion_sql(version="2")),
        ("fk_cotizacion_catalogo", cotizacion_sql(version_catalogo="9")),
        ("ck_oferta_duracion", oferta_sql(duracion="0")),
        ("ck_oferta_duracion", oferta_sql(duracion="-1")),
        ("ck_cotizacion_duracion", cotizacion_sql(duracion="0")),
        ("ck_cotizacion_duracion", cotizacion_sql(duracion="-5")),
    ],
)
def test_las_restricciones_rechazan_datos_imposibles(
    base: Database, catalogo_v1: CatalogoVigente, restriccion: str, sentencia: str
) -> None:
    with pytest.raises(IntegrityError) as capturado:
        with base.engine.begin() as conexion:
            conexion.execute(text(sentencia))
    assert isinstance(capturado.value.orig, psycopg.errors.IntegrityError)
    assert capturado.value.orig.diag.constraint_name == restriccion


def test_downgrade_a_base_y_upgrade_otra_vez(base_integracion: Database) -> None:
    migrar(base_integracion, command.downgrade, "base")
    assert not ESQUEMAS & set(inspect(base_integracion.engine).get_schema_names())
    migrar(base_integracion, command.upgrade, "head")
    assert ESQUEMAS <= set(inspect(base_integracion.engine).get_schema_names())
    assert diferencias_con_orm(base_integracion) == []
