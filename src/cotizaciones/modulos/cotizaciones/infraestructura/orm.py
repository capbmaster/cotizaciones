from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cotizaciones.seedwork.infraestructura.orm import BaseSQL
from cotizaciones.seedwork.infraestructura.serializacion import Documento

_RED = "tipo_red IN ('GENERAL_HDA', 'HOMOLOGADA_PARTNER')"
_RED_PARTNER = (
    "(tipo_red <> 'GENERAL_HDA' OR id_partner IS NULL) "
    "AND (tipo_red <> 'HOMOLOGADA_PARTNER' OR id_partner IS NOT NULL)"
)
_MOTIVO = "motivo IS NULL OR motivo IN ('SIN_OFERTA_PARA_CATEGORIA', 'SIN_PROVEEDOR_EN_RED')"
# E3 (Paso 54): columna aditiva nullable en ofertas_catalogo y cotizaciones.
_DURACION = "duracion_estimada_minutos IS NULL OR duracion_estimada_minutos > 0"
_RESULTADO = (
    "(estado = 'PROPUESTA' AND id_proveedor IS NOT NULL AND importe_menor IS NOT NULL "
    "AND importe_menor > 0 AND moneda IS NOT NULL AND motivo IS NULL) "
    "OR (estado = 'RECHAZADA' AND id_proveedor IS NULL AND importe_menor IS NULL "
    "AND moneda IS NULL AND motivo IS NOT NULL)"
)


class CatalogoSQL(BaseSQL):
    __tablename__ = "catalogos"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_catalogo_version"),
        Index("uq_catalogo_activo", "activo", unique=True, postgresql_where=text("activo")),
        {"schema": "cotizaciones"},
    )
    version: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    huella: Mapped[str]
    cargado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activo: Mapped[bool] = mapped_column(default=False, server_default=text("false"))


class OfertaCatalogoSQL(BaseSQL):
    __tablename__ = "ofertas_catalogo"
    __table_args__ = (
        CheckConstraint(_RED, name="ck_oferta_tipo_red"),
        CheckConstraint("importe_menor > 0", name="ck_oferta_importe"),
        CheckConstraint("moneda ~ '^[A-Z]{3}$'", name="ck_oferta_moneda"),
        CheckConstraint(_RED_PARTNER, name="ck_oferta_red_partner"),
        CheckConstraint(_DURACION, name="ck_oferta_duracion"),
        UniqueConstraint(
            "version_catalogo",
            "categoria",
            "tipo_red",
            "id_partner",
            "id_proveedor",
            name="uq_oferta_catalogo",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_oferta_version_categoria", "version_catalogo", "categoria"),
        {"schema": "cotizaciones"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    version_catalogo: Mapped[int] = mapped_column(
        ForeignKey("cotizaciones.catalogos.version", name="fk_oferta_catalogo")
    )
    id_proveedor: Mapped[UUID]
    categoria: Mapped[str]
    tipo_red: Mapped[str]
    id_partner: Mapped[UUID | None]
    importe_menor: Mapped[int] = mapped_column(BigInteger)
    moneda: Mapped[str]
    duracion_estimada_minutos: Mapped[int | None]


class CotizacionSQL(BaseSQL):
    __tablename__ = "cotizaciones"
    __table_args__ = (
        UniqueConstraint("id_peticion", name="uq_cotizacion_peticion"),
        CheckConstraint("version_cotizacion = 1", name="ck_cotizacion_version"),
        CheckConstraint("estado IN ('PROPUESTA', 'RECHAZADA')", name="ck_cotizacion_estado"),
        CheckConstraint(_MOTIVO, name="ck_cotizacion_motivo"),
        CheckConstraint(_RESULTADO, name="ck_cotizacion_resultado"),
        CheckConstraint(_DURACION, name="ck_cotizacion_duracion"),
        Index("ix_cotizacion_trabajo", "id_trabajo"),
        Index("ix_cotizacion_resuelta", "resuelta_en", "id"),
        {"schema": "cotizaciones"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    id_peticion: Mapped[UUID]
    id_trabajo: Mapped[UUID]
    id_solicitud: Mapped[UUID]
    id_partner: Mapped[UUID]
    peticion: Mapped[Documento] = mapped_column(JSONB)
    id_comando_origen: Mapped[UUID]
    correlacion: Mapped[UUID]
    causacion: Mapped[UUID]
    instante_comando: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version_catalogo: Mapped[int] = mapped_column(
        ForeignKey("cotizaciones.catalogos.version", name="fk_cotizacion_catalogo")
    )
    version_cotizacion: Mapped[int]
    estado: Mapped[str]
    id_proveedor: Mapped[UUID | None]
    importe_menor: Mapped[int | None] = mapped_column(BigInteger)
    moneda: Mapped[str | None]
    motivo: Mapped[str | None]
    duracion_estimada_minutos: Mapped[int | None]
    resuelta_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    registrada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
