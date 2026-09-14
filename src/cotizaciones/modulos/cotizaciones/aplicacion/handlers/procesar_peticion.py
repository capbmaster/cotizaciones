from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.aplicacion.excepciones import ConflictoPeticion
from cotizaciones.modulos.cotizaciones.aplicacion.unidad_trabajo import (
    UnidadTrabajoCotizaciones,
)
from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.seedwork.aplicacion.identificadores import GeneradorIdentificadores
from cotizaciones.seedwork.aplicacion.reintentos import reintentar_colision
from cotizaciones.seedwork.aplicacion.reloj import Reloj


@dataclass(frozen=True)
class ResultadoProcesamiento:
    id_cotizacion: UUID | None
    nueva: bool


@dataclass(frozen=True)
class ProcesarPeticionHandler:
    consumidor: ClassVar[str] = "cotizaciones.procesar_peticion"
    crear_unidad: Callable[[], UnidadTrabajoCotizaciones]
    reloj: Reloj
    identificadores: GeneradorIdentificadores

    @reintentar_colision
    def __call__(self, comando: ProcesarPeticionCotizacion) -> ResultadoProcesamiento:
        with self.crear_unidad() as unidad:
            existente = unidad.cotizaciones.obtener_por_peticion(comando.datos.id_peticion)
            if existente is not None:
                if existente.peticion != comando.datos:
                    raise ConflictoPeticion("La peticion ya fue resuelta con otros datos")
                if unidad.registrar_recepcion(self.consumidor, comando):
                    unidad.confirmar()
                return ResultadoProcesamiento(id_cotizacion=existente.id, nueva=False)
            if not unidad.registrar_recepcion(self.consumidor, comando):
                return ResultadoProcesamiento(id_cotizacion=None, nueva=False)
            # El catálogo se lee después de descartar duplicados: una petición ya resuelta
            # conserva su resultado aunque cambie la versión activa.
            catalogo = unidad.catalogos.obtener_vigente()
            cotizacion = Cotizacion.resolver(
                id=self.identificadores.generar(),
                peticion=comando.datos,
                origen=comando.origen,
                catalogo=catalogo,
                id_evento=self.identificadores.generar(),
                instante=self.reloj.ahora(),
            )
            unidad.cotizaciones.guardar(cotizacion)
            for evento in cotizacion.retirar_eventos():
                unidad.registrar_salida(evento)
            unidad.confirmar()
            return ResultadoProcesamiento(id_cotizacion=cotizacion.id, nueva=True)
