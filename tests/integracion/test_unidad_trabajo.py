from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from cotizaciones.config.database import Database
from cotizaciones.config.persistencia import crear_uow_cotizaciones
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoNoDisponible
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente
from cotizaciones.modulos.cotizaciones.infraestructura.orm import CotizacionSQL
from cotizaciones.modulos.cotizaciones.infraestructura.repositorios import (
    RepositorioCotizacionesSQL,
)
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import serializar_comando
from cotizaciones.seedwork.aplicacion.excepciones import ConflictoMensaje
from cotizaciones.seedwork.infraestructura.inbox import EntradaSQL
from cotizaciones.seedwork.infraestructura.outbox import EventoSQL, SalidaSQL
from cotizaciones.seedwork.infraestructura.unidad_trabajo_sqlalchemy import UnidadTrabajoSQL

from ..unitarias.aplicacion.datos import comando_peticion
from ..unitarias.dominio.datos import catalogo_laboratorio, uuid_lab
from .datos import contar, procesar_sql, registrar_catalogo

TABLAS = (CotizacionSQL, EntradaSQL, SalidaSQL, EventoSQL)


def conteos(base: Database) -> tuple[int, ...]:
    return tuple(contar(base, tabla) for tabla in TABLAS)


@pytest.mark.parametrize("fallo", ["inbox", "negocio", "outbox", "commit"])
def test_un_fallo_revierte_cotizacion_inbox_y_salida(
    base: Database, catalogo_v1: CatalogoVigente, fallo: str
) -> None:
    procesar = procesar_sql(base)
    clase, metodo = {
        "inbox": (UnidadTrabajoSQL, "preparar_entrada"),
        "negocio": (RepositorioCotizacionesSQL, "guardar"),
        "outbox": (UnidadTrabajoSQL, "registrar_salida"),
        "commit": (Session, "commit"),
    }[fallo]
    original = getattr(clase, metodo)

    def fallar(*argumentos: Any, **opciones: Any) -> None:
        if fallo != "commit":
            original(*argumentos, **opciones)
        raise RuntimeError("Fallo inyectado")

    with patch.object(clase, metodo, fallar), pytest.raises(RuntimeError, match="inyectado"):
        procesar(comando_peticion())
    assert conteos(base) == (0, 0, 0, 0)
    assert procesar(comando_peticion()).nueva is True
    assert conteos(base) == (1, 1, 1, 1)


def test_catalogo_ausente_no_deja_cotizacion_inbox_ni_salida(base: Database) -> None:
    with pytest.raises(CatalogoNoDisponible):
        procesar_sql(base)(comando_peticion())
    assert conteos(base) == (0, 0, 0, 0)


def test_catalogo_registrado_sin_activar_equivale_a_catalogo_ausente(base: Database) -> None:
    registrar_catalogo(base, catalogo_laboratorio(), activar=False)
    with pytest.raises(CatalogoNoDisponible):
        procesar_sql(base)(comando_peticion())
    assert conteos(base) == (0, 0, 0, 0)


def test_inbox_por_consumidor_con_rollback_y_conflicto(base: Database) -> None:
    comando = comando_peticion()
    with crear_uow_cotizaciones(base) as unidad:
        assert unidad.registrar_recepcion("primero", comando)  # sin confirmar: se revierte
    with crear_uow_cotizaciones(base) as unidad:
        assert unidad.registrar_recepcion("primero", comando)
        assert unidad.registrar_recepcion("segundo", comando)
        unidad.confirmar()
    with crear_uow_cotizaciones(base) as unidad:
        assert not unidad.registrar_recepcion("primero", comando)
        with pytest.raises(ConflictoMensaje):
            unidad.registrar_recepcion("primero", comando_peticion(categoria="electricidad"))
    with base.session_factory() as sesion:
        documentos = list(sesion.scalars(select(EntradaSQL.documento)))
    assert documentos == [serializar_comando(comando)] * 2


def test_mismo_comando_con_otra_peticion_es_conflicto_de_mensaje(
    base: Database, catalogo_v1: CatalogoVigente
) -> None:
    procesar = procesar_sql(base)
    procesar(comando_peticion())
    with pytest.raises(ConflictoMensaje):
        procesar(comando_peticion(id_peticion=uuid_lab("0025")))
    assert conteos(base) == (1, 1, 1, 1)


def test_sesiones_distintas_y_cierre(base: Database) -> None:
    primera = crear_uow_cotizaciones(base)
    segunda = crear_uow_cotizaciones(base)
    with primera, segunda:
        assert primera.sesion is not segunda.sesion
        assert primera.sesion.scalar(select(func.pg_backend_pid())) != segunda.sesion.scalar(
            select(func.pg_backend_pid())
        )
    with pytest.raises(RuntimeError, match="inactiva"):
        assert primera.sesion is not None
    assert isinstance(base.engine.pool, QueuePool)
    assert base.engine.pool.checkedout() == 0
