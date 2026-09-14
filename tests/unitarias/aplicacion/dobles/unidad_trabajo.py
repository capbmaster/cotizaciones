from copy import deepcopy
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self
from uuid import UUID

from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente
from cotizaciones.seedwork.aplicacion.excepciones import ColisionPersistencia, ConflictoMensaje
from cotizaciones.seedwork.dominio.eventos import EventoDominio

from .repositorios import RepositorioCatalogoMemoria, RepositorioCotizacionesMemoria


@dataclass
class EstadoMemoria:
    catalogo: CatalogoVigente | None = None
    cotizaciones: dict[UUID, Cotizacion] = field(default_factory=dict)
    recepciones: dict[tuple[str, UUID], ProcesarPeticionCotizacion] = field(default_factory=dict)
    salidas: list[EventoDominio] = field(default_factory=list)


@dataclass
class ConfirmacionAjena:
    """Lo que otra réplica confirma mientras esta unidad todavía trabaja."""

    consumidor: str
    comando: ProcesarPeticionCotizacion
    cotizacion: Cotizacion

    def aplicar(self, estado: EstadoMemoria) -> None:
        estado.cotizaciones[self.cotizacion.peticion.id_peticion] = self.cotizacion
        estado.recepciones[(self.consumidor, self.comando.origen.id_comando)] = self.comando
        estado.salidas.extend(self.cotizacion.retirar_eventos())


@dataclass
class AlmacenMemoria:
    """Estado confirmado, compartido por todas las unidades de trabajo de una prueba."""

    estado: EstadoMemoria = field(default_factory=EstadoMemoria)
    fallar_al_guardar: bool = False
    fallar_al_registrar_salida: bool = False
    colision_con: ConfirmacionAjena | None = None
    aperturas: int = 0
    confirmaciones: int = 0
    consultas_catalogo: int = 0


class UnidadTrabajoMemoria:
    """Transaccional: trabaja sobre una copia y solo la publica en el almacén al confirmar."""

    estado: EstadoMemoria
    cotizaciones: RepositorioCotizacionesMemoria
    catalogos: RepositorioCatalogoMemoria

    def __init__(self, almacen: AlmacenMemoria) -> None:
        self.almacen = almacen
        self.activa = False
        self._copiar_estado_confirmado()

    def __enter__(self) -> Self:
        if self.activa:
            raise RuntimeError("Unidad de trabajo ya activa")
        self._copiar_estado_confirmado()
        self.activa = True
        self.almacen.aperturas += 1
        return self

    def __exit__(
        self,
        tipo_error: type[BaseException] | None,
        error: BaseException | None,
        traza: TracebackType | None,
    ) -> None:
        self.revertir()

    def registrar_recepcion(self, consumidor: str, comando: ProcesarPeticionCotizacion) -> bool:
        self._verificar_activa()
        clave = (consumidor, comando.origen.id_comando)
        anterior = self.estado.recepciones.get(clave)
        if anterior is not None:
            if anterior != comando:
                raise ConflictoMensaje("El comando ya fue recibido con otro contenido")
            return False
        self.estado.recepciones[clave] = comando
        return True

    def registrar_salida(self, evento: EventoDominio) -> None:
        self._verificar_activa()
        if self.almacen.fallar_al_registrar_salida:
            raise RuntimeError("Fallo al registrar la salida")
        self.estado.salidas.append(evento)

    def confirmar(self) -> None:
        self._verificar_activa()
        self.almacen.estado = deepcopy(self.estado)
        self.almacen.confirmaciones += 1
        self.activa = False

    def revertir(self) -> None:
        self._copiar_estado_confirmado()
        self.activa = False

    def _copiar_estado_confirmado(self) -> None:
        self.estado = deepcopy(self.almacen.estado)
        self.cotizaciones = RepositorioCotizacionesMemoria(
            self.estado.cotizaciones, self._antes_de_guardar
        )
        self.catalogos = RepositorioCatalogoMemoria(self.estado.catalogo, self._al_consultar)

    def _antes_de_guardar(self, cotizacion: Cotizacion) -> None:
        self._verificar_activa()
        if self.almacen.fallar_al_guardar:
            raise RuntimeError("Fallo al guardar la cotizacion")
        ajena = self.almacen.colision_con
        if ajena is not None:
            self.almacen.colision_con = None
            ajena.aplicar(self.almacen.estado)
            raise ColisionPersistencia("uq_cotizacion_peticion")

    def _al_consultar(self) -> None:
        self._verificar_activa()
        self.almacen.consultas_catalogo += 1

    def _verificar_activa(self) -> None:
        if not self.activa:
            raise RuntimeError("Unidad de trabajo inactiva")
