from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4, uuid5

from sqlalchemy import DateTime, Index, UniqueConstraint, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from cotizaciones.seedwork.aplicacion.publicacion import Publicacion
from cotizaciones.seedwork.infraestructura.orm import BaseSQL
from cotizaciones.seedwork.infraestructura.serializacion import Documento


class EventoSQL(BaseSQL):
    __tablename__ = "eventos"
    __table_args__ = {"schema": "mensajeria"}
    id_evento: Mapped[UUID] = mapped_column(primary_key=True)
    documento: Mapped[Documento] = mapped_column(JSONB)


class SalidaSQL(BaseSQL):
    __tablename__ = "outbox"
    __table_args__ = (
        UniqueConstraint("id_evento", "destino", name="uq_salida_destino"),
        Index("ix_salida_pendiente", "enviada_en", "proximo_intento", "vence_en"),
        {"schema": "mensajeria"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    id_evento: Mapped[UUID]
    destino: Mapped[str]
    documento: Mapped[Documento] = mapped_column(JSONB)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    proximo_intento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    enviada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    propietario: Mapped[str | None]
    token: Mapped[UUID | None]
    vence_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intentos: Mapped[int] = mapped_column(default=0, server_default="0")
    ultimo_error: Mapped[str | None]


@dataclass(frozen=True)
class Reserva:
    publicacion: Publicacion
    token: UUID
    propietario: str
    vence_en: datetime

    @property
    def id(self) -> UUID:
        return self.publicacion.id


class RepositorioOutbox:
    def __init__(
        self, crear_sesion: Callable[[], Session], destinos: tuple[str, ...] | None = None
    ) -> None:
        self.crear_sesion = crear_sesion
        self.destinos = destinos

    def reclamar(self, propietario: str, limite: int, duracion: timedelta) -> list[Reserva]:
        if not propietario.strip() or limite <= 0 or duracion.total_seconds() <= 0:
            raise ValueError("Reserva invalida")
        with self.crear_sesion() as sesion, sesion.begin():
            ahora = cast(datetime, sesion.scalar(select(func.clock_timestamp())))
            filas = sesion.scalars(
                select(SalidaSQL)
                .where(
                    SalidaSQL.enviada_en.is_(None),
                    SalidaSQL.destino.in_(self.destinos) if self.destinos is not None else true(),
                    SalidaSQL.proximo_intento <= ahora,
                    or_(SalidaSQL.vence_en.is_(None), SalidaSQL.vence_en <= ahora),
                )
                .order_by(SalidaSQL.creada_en, SalidaSQL.id)
                .limit(limite)
                .with_for_update(skip_locked=True)
            )
            reservas = []
            for fila in filas:
                fila.token = uuid4()
                fila.propietario = propietario
                fila.vence_en = ahora + duracion
                fila.intentos += 1
                reservas.append(
                    Reserva(
                        Publicacion(
                            fila.id, fila.id_evento, fila.destino, deepcopy(fila.documento)
                        ),
                        fila.token,
                        propietario,
                        fila.vence_en,
                    )
                )
            return reservas

    def confirmar(self, reserva: Reserva) -> bool:
        return self._actualizar(
            reserva,
            dict(
                enviada_en=func.clock_timestamp(),
                token=None,
                propietario=None,
                vence_en=None,
                ultimo_error=None,
            ),
        )

    def reprogramar(self, reserva: Reserva, error: str, demora: timedelta) -> bool:
        if demora.total_seconds() < 0:
            raise ValueError("Demora negativa")
        return self._actualizar(
            reserva,
            dict(
                ultimo_error=error[:2000],
                proximo_intento=func.clock_timestamp() + demora,
                token=None,
                propietario=None,
                vence_en=None,
            ),
        )

    def _actualizar(self, reserva: Reserva, valores: Documento) -> bool:
        with self.crear_sesion() as sesion, sesion.begin():
            identidad = sesion.scalar(
                update(SalidaSQL)
                .where(
                    SalidaSQL.id == reserva.id,
                    SalidaSQL.token == reserva.token,
                    SalidaSQL.propietario == reserva.propietario,
                    SalidaSQL.vence_en > func.clock_timestamp(),
                    SalidaSQL.enviada_en.is_(None),
                )
                .values(**valores)
                .returning(SalidaSQL.id)
            )
            return identidad is not None

    def hay_pendientes_fuera_de(self, destinos_admitidos: tuple[str, ...]) -> bool:
        with self.crear_sesion() as sesion:
            pendiente = sesion.scalar(
                select(SalidaSQL.id)
                .where(
                    SalidaSQL.enviada_en.is_(None),
                    SalidaSQL.destino.not_in(destinos_admitidos),
                )
                .limit(1)
            )
            return pendiente is not None

    def inspeccionar(self, limite: int = 100) -> list[Documento]:
        if limite <= 0:
            raise ValueError("Limite invalido")
        with self.crear_sesion() as sesion:
            filas = sesion.scalars(
                select(SalidaSQL)
                .where(SalidaSQL.enviada_en.is_(None))
                .order_by(SalidaSQL.creada_en, SalidaSQL.id)
                .limit(limite)
            )
            return [
                dict(
                    id=str(fila.id),
                    id_evento=str(fila.id_evento),
                    destino=fila.destino,
                    intentos=fila.intentos,
                    ultimo_error=fila.ultimo_error,
                    propietario=fila.propietario,
                    vence_en=fila.vence_en,
                    proximo_intento=fila.proximo_intento,
                )
                for fila in filas
            ]

    def metricas(self) -> Documento:
        with self.crear_sesion() as sesion:
            cantidad, primera = sesion.execute(
                select(func.count(), func.min(SalidaSQL.creada_en)).where(
                    SalidaSQL.enviada_en.is_(None)
                )
            ).one()
            ahora = cast(datetime, sesion.scalar(select(func.clock_timestamp())))
            return dict(
                pendientes=cantidad,
                antiguedad_segundos=(ahora - primera).total_seconds() if primera else 0,
            )


ESPACIO_ENTREGAS = UUID("6f1d3b2a-8c4e-4f7a-9b1d-2e3c4d5f6a70")


class RepositorioSalidasSQL:
    def __init__(self, sesion: Session) -> None:
        self.sesion = sesion

    def guardar(self, id_evento: UUID, documento: Documento, destinos: Sequence[str]) -> None:
        if len(set(destinos)) != len(destinos) or any(not destino.strip() for destino in destinos):
            raise ValueError("Destinos de salida invalidos")
        nuevo = self.sesion.scalar(
            insert(EventoSQL)
            .values(id_evento=id_evento, documento=documento)
            .on_conflict_do_nothing(index_elements=[EventoSQL.id_evento])
            .returning(EventoSQL.id_evento)
        )
        if nuevo is None:
            anterior = self.sesion.scalar(
                select(EventoSQL.documento).where(EventoSQL.id_evento == id_evento)
            )
            if anterior != documento:
                raise ValueError("El evento archivado ya tiene otro contenido")
        for destino in destinos:
            self.sesion.add(
                SalidaSQL(
                    id=uuid5(ESPACIO_ENTREGAS, f"{id_evento}:{destino}"),
                    id_evento=id_evento,
                    destino=destino,
                    documento=documento,
                )
            )
