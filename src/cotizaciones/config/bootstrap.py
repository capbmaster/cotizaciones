from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ProcesarPeticionHandler,
)
from cotizaciones.modulos.cotizaciones.aplicacion.unidad_trabajo import (
    UnidadTrabajoCotizaciones,
)
from cotizaciones.seedwork.aplicacion.identificadores import GeneradorIdentificadores
from cotizaciones.seedwork.aplicacion.reloj import Reloj
from cotizaciones.seedwork.infraestructura.identificadores import IdentificadoresAleatorios
from cotizaciones.seedwork.infraestructura.reloj import RelojActual

if TYPE_CHECKING:
    from cotizaciones.config.database import Database
    from cotizaciones.config.settings import Settings
    from cotizaciones.modulos.cotizaciones.aplicacion.handlers.consultar_cotizaciones import (
        ConsultarCotizacionHandler,
        ListarCotizacionesHandler,
    )
    from cotizaciones.modulos.cotizaciones.infraestructura.consumidor_peticiones import (
        ConsumidorPeticiones,
    )
    from cotizaciones.seedwork.infraestructura.despacho_outbox import DespachadorOutbox


def componer_procesamiento(
    crear_unidad: Callable[[], UnidadTrabajoCotizaciones],
    reloj: Reloj,
    identificadores: GeneradorIdentificadores,
) -> ProcesarPeticionHandler:
    return ProcesarPeticionHandler(crear_unidad, reloj, identificadores)


def componer_procesamiento_sql(base: "Database") -> ProcesarPeticionHandler:
    from cotizaciones.config.persistencia import crear_uow_cotizaciones

    return componer_procesamiento(
        lambda: crear_uow_cotizaciones(base), RelojActual(), IdentificadoresAleatorios()
    )


def componer_consumidor_peticiones(
    base: "Database", configuracion: "Settings"
) -> "ConsumidorPeticiones":
    from cotizaciones.modulos.cotizaciones.infraestructura.consumidor_peticiones import (
        ConsumidorPeticiones,
    )

    return ConsumidorPeticiones(
        configuracion.pulsar_url,
        configuracion.topico_peticiones,
        configuracion.suscripcion_peticiones,
        componer_procesamiento_sql(base),
        tamano_cola=configuracion.receptor_cola,
        demora_nack_ms=configuracion.demora_nack_ms,
        timeout_segundos=configuracion.pulsar_timeout_segundos,
        retardo_laboratorio_ms=configuracion.retardo_laboratorio_ms,
    )


def _clave_trabajo(mensaje: Any) -> str:
    return str(mensaje.id_trabajo)


def componer_despacho_resultados(
    base: "Database", configuracion: "Settings"
) -> tuple["DespachadorOutbox", Callable[[], None]]:
    from uuid import uuid4

    from pulsar.schema import AvroSchema

    from cotizaciones.config.rutas import (
        DESTINO_RECHAZADA,
        DESTINO_REGISTRADA,
        DESTINOS_ADMITIDOS,
    )
    from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.eventos import (
        CotizacionRechazadaV1,
        CotizacionRegistradaV1,
    )
    from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
        mensaje_rechazada,
        mensaje_registrada,
    )
    from cotizaciones.seedwork.infraestructura.despacho_outbox import DespachadorOutbox
    from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox
    from cotizaciones.seedwork.infraestructura.publicador_pulsar import (
        DestinoPulsar,
        PublicadorPulsar,
    )

    publicador = PublicadorPulsar(
        configuracion.pulsar_url,
        {
            DESTINO_REGISTRADA: DestinoPulsar(
                configuracion.topico_registrada,
                AvroSchema(CotizacionRegistradaV1),
                mensaje_registrada,
                _clave_trabajo,
            ),
            DESTINO_RECHAZADA: DestinoPulsar(
                configuracion.topico_rechazada,
                AvroSchema(CotizacionRechazadaV1),
                mensaje_rechazada,
                _clave_trabajo,
            ),
        },
        timeout_segundos=configuracion.pulsar_timeout_segundos,
    )
    despachador = DespachadorOutbox(
        RepositorioOutbox(base.session_factory, DESTINOS_ADMITIDOS),
        publicador,
        f"cotizaciones-{uuid4()}",
    )
    return despachador, publicador.cerrar


def componer_consulta(base: "Database") -> "ConsultarCotizacionHandler":
    from cotizaciones.modulos.cotizaciones.aplicacion.handlers.consultar_cotizaciones import (
        ConsultarCotizacionHandler,
    )
    from cotizaciones.modulos.cotizaciones.infraestructura.repositorios import (
        RepositorioLecturaCotizacionesSQL,
    )

    return ConsultarCotizacionHandler(RepositorioLecturaCotizacionesSQL(base.session_factory))


def componer_listado(base: "Database") -> "ListarCotizacionesHandler":
    from cotizaciones.modulos.cotizaciones.aplicacion.handlers.consultar_cotizaciones import (
        ListarCotizacionesHandler,
    )
    from cotizaciones.modulos.cotizaciones.infraestructura.repositorios import (
        RepositorioLecturaCotizacionesSQL,
    )

    return ListarCotizacionesHandler(RepositorioLecturaCotizacionesSQL(base.session_factory))
