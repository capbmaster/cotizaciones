from collections.abc import Callable, Sequence
from types import TracebackType
from typing import Self
from uuid import UUID

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cotizaciones.seedwork.aplicacion.excepciones import ColisionPersistencia
from cotizaciones.seedwork.dominio.eventos import EventoDominio
from cotizaciones.seedwork.infraestructura.inbox import preparar
from cotizaciones.seedwork.infraestructura.outbox import RepositorioSalidasSQL
from cotizaciones.seedwork.infraestructura.serializacion import Documento


class UnidadTrabajoSQL:
    restricciones_reintentables: frozenset[str] = frozenset()

    def __init__(
        self,
        crear_sesion: Callable[[], Session],
        serializar: Callable[[EventoDominio], Documento],
        destinos: Callable[[EventoDominio], Sequence[str]],
    ) -> None:
        self.crear_sesion = crear_sesion
        self.serializar = serializar
        self.destinos = destinos
        self._sesion: Session | None = None
        self._activa = False

    @property
    def sesion(self) -> Session:
        if self._sesion is None or not self._activa:
            raise RuntimeError("Unidad de trabajo inactiva")
        return self._sesion

    def __enter__(self) -> Self:
        if self._sesion is not None:
            raise RuntimeError("Unidad de trabajo ya abierta")
        self._sesion = self.crear_sesion()
        self._activa = True
        try:
            self.sesion.begin()
            self._crear_repositorios()
        except BaseException:
            self._sesion.close()
            self._sesion = None
            self._activa = False
            raise
        return self

    def _crear_repositorios(self) -> None:
        raise NotImplementedError

    def __exit__(
        self,
        tipo_error: type[BaseException] | None,
        error: BaseException | None,
        traza: TracebackType | None,
    ) -> None:
        try:
            self.revertir()
        finally:
            if self._sesion is not None:
                self._sesion.close()
            self._sesion = None
        if isinstance(error, IntegrityError) and isinstance(error.orig, UniqueViolation):
            if error.orig.diag.constraint_name in self.restricciones_reintentables:
                raise ColisionPersistencia("Conflicto concurrente de persistencia") from error

    def confirmar(self) -> None:
        self.sesion.flush()
        self.sesion.commit()
        self._activa = False

    def revertir(self) -> None:
        if self._sesion is not None:
            self._sesion.rollback()
        self._activa = False

    def preparar_entrada(self, consumidor: str, id_mensaje: UUID, documento: Documento) -> bool:
        return preparar(self.sesion, consumidor, id_mensaje, documento)

    def registrar_salida(self, evento: EventoDominio) -> None:
        RepositorioSalidasSQL(self.sesion).guardar(
            evento.id_evento, self.serializar(evento), self.destinos(evento)
        )
