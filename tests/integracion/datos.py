from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import func, select, text

from cotizaciones.config.bootstrap import componer_procesamiento_sql
from cotizaciones.config.database import Database
from cotizaciones.config.persistencia import crear_uow_cotizaciones
from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ProcesarPeticionHandler,
)
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import huella_catalogo
from cotizaciones.seedwork.dominio.eventos import EventoDominio
from cotizaciones.seedwork.infraestructura.orm import BaseSQL

from ..unitarias.dominio.datos import ID_EVENTO, cotizacion_resuelta


def procesar_sql(base: Database) -> ProcesarPeticionHandler:
    return componer_procesamiento_sql(base)


def contar(base: Database, modelo: type[BaseSQL]) -> int:
    with base.session_factory() as sesion:
        return sesion.scalar(select(func.count()).select_from(modelo)) or 0


def marcas_sin_efecto(base: Database) -> int:
    """Marcas de inbox cuya petición no tiene cotización: deben ser cero siempre."""
    with base.engine.connect() as conexion:
        cantidad = conexion.scalar(
            text(
                "SELECT count(*) FROM mensajeria.inbox i WHERE NOT EXISTS ("
                " SELECT 1 FROM cotizaciones.cotizaciones c"
                " WHERE c.id_peticion = (i.documento->'datos'->>'id_peticion')::uuid)"
            )
        )
        return int(cantidad or 0)


def salidas_enviadas(base: Database) -> int:
    with base.engine.connect() as conexion:
        cantidad = conexion.scalar(
            text("SELECT count(*) FROM mensajeria.outbox WHERE enviada_en IS NOT NULL")
        )
        return int(cantidad or 0)


def salidas_pendientes(base: Database) -> int:
    with base.engine.connect() as conexion:
        cantidad = conexion.scalar(
            text("SELECT count(*) FROM mensajeria.outbox WHERE enviada_en IS NULL")
        )
        return int(cantidad or 0)


def registrar_catalogo(base: Database, catalogo: CatalogoVigente, *, activar: bool = True) -> None:
    with crear_uow_cotizaciones(base) as unidad:
        unidad.catalogos.registrar_version(catalogo, huella_catalogo(catalogo))
        if activar:
            unidad.catalogos.activar(catalogo.version)
        unidad.confirmar()


def evento_resuelto(id_evento: UUID = ID_EVENTO) -> EventoDominio:
    (evento,) = cotizacion_resuelta(id_evento=id_evento).retirar_eventos()
    return evento


def registrar_salidas(
    base: Database, eventos: Iterable[EventoDominio], destinos: tuple[str, ...] | None = None
) -> None:
    unidad = crear_uow_cotizaciones(base)
    if destinos is not None:
        unidad.destinos = lambda evento: destinos
    with unidad:
        for evento in eventos:
            unidad.registrar_salida(evento)
        unidad.confirmar()
