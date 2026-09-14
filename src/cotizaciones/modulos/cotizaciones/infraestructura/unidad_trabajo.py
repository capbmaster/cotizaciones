from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.infraestructura.repositorios import (
    RepositorioCatalogoSQL,
    RepositorioCotizacionesSQL,
)
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import serializar_comando
from cotizaciones.seedwork.infraestructura.unidad_trabajo_sqlalchemy import UnidadTrabajoSQL


class UnidadTrabajoCotizacionesSQL(UnidadTrabajoSQL):
    restricciones_reintentables = frozenset({"uq_cotizacion_peticion"})
    cotizaciones: RepositorioCotizacionesSQL
    catalogos: RepositorioCatalogoSQL

    def _crear_repositorios(self) -> None:
        self.cotizaciones = RepositorioCotizacionesSQL(self.sesion)
        self.catalogos = RepositorioCatalogoSQL(self.sesion)

    def registrar_recepcion(self, consumidor: str, comando: ProcesarPeticionCotizacion) -> bool:
        return self.preparar_entrada(
            consumidor, comando.origen.id_comando, serializar_comando(comando)
        )
