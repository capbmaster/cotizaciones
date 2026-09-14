from cotizaciones.config.database import Database
from cotizaciones.config.rutas import DESTINOS_ADMITIDOS, destinos_evento
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import serializar_evento
from cotizaciones.modulos.cotizaciones.infraestructura.unidad_trabajo import (
    UnidadTrabajoCotizacionesSQL,
)
from cotizaciones.seedwork.infraestructura.orm import BaseSQL
from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox

# Importar la UoW registra todas las tablas (módulo, inbox, outbox y archivo de eventos).
metadata = BaseSQL.metadata


def crear_uow_cotizaciones(base: Database) -> UnidadTrabajoCotizacionesSQL:
    return UnidadTrabajoCotizacionesSQL(base.session_factory, serializar_evento, destinos_evento)


def verificar_destinos(base: Database) -> None:
    outbox = RepositorioOutbox(base.session_factory)
    if outbox.hay_pendientes_fuera_de(DESTINOS_ADMITIDOS):
        raise ValueError(
            "Hay destinos pendientes desconocidos; inspeccionar outbox antes de iniciar"
        )
