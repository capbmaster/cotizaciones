from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from cotizaciones.seedwork.aplicacion.excepciones import ConflictoMensaje
from cotizaciones.seedwork.infraestructura.orm import BaseSQL
from cotizaciones.seedwork.infraestructura.serializacion import Documento


class EntradaSQL(BaseSQL):
    __tablename__ = "inbox"
    __table_args__ = {"schema": "mensajeria"}
    nombre_consumidor: Mapped[str] = mapped_column(primary_key=True)
    id_mensaje: Mapped[UUID] = mapped_column(primary_key=True)
    documento: Mapped[Documento] = mapped_column(JSONB)
    procesada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def preparar(sesion: Session, consumidor: str, id_mensaje: UUID, documento: Documento) -> bool:
    if not consumidor.strip():
        raise ValueError("Consumidor vacio")
    nueva = sesion.scalar(
        insert(EntradaSQL)
        .values(nombre_consumidor=consumidor, id_mensaje=id_mensaje, documento=documento)
        .on_conflict_do_nothing(
            index_elements=[EntradaSQL.nombre_consumidor, EntradaSQL.id_mensaje]
        )
        .returning(EntradaSQL.id_mensaje)
    )
    if nueva is not None:
        return True
    anterior = sesion.scalar(
        select(EntradaSQL.documento).where(
            EntradaSQL.nombre_consumidor == consumidor, EntradaSQL.id_mensaje == id_mensaje
        )
    )
    if anterior != documento:
        raise ConflictoMensaje("El mensaje ya fue recibido con otro contenido")
    return False
