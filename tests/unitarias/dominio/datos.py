from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    DatosPeticion,
    Dinero,
    OfertaCatalogo,
    OrigenComando,
    TipoRed,
    TipoSolicitud,
)


def uuid_lab(sufijo: str) -> UUID:
    """`uuid_lab("0021")` → 00000000-0000-0000-0000-000000000021 (abreviatura de 00 §10)."""
    return UUID(f"00000000-0000-0000-0000-{sufijo:0>12}")


ID_SOLICITUD = uuid_lab("0001")
PARTNER_LAB = uuid_lab("0002")
ID_POLITICA = uuid_lab("0003")
PARTNER_SIN_HOMOLOGADOS = uuid_lab("0009")
CAUSACION = uuid_lab("000f")
ID_TRABAJO = uuid_lab("0020")
ID_PETICION = uuid_lab("0021")
ID_COMANDO = uuid_lab("0022")
ID_COTIZACION = uuid_lab("0030")
ID_EVENTO = uuid_lab("0031")

A101 = uuid_lab("a101")
A102 = uuid_lab("a102")
B101 = uuid_lab("b101")
A201 = uuid_lab("a201")
A301 = uuid_lab("a301")

INSTANTE_COMANDO = datetime(2026, 9, 12, 15, 0, 3, tzinfo=UTC)
INSTANTE_RESULTADO = datetime(2026, 9, 12, 15, 0, 4, tzinfo=UTC)


def oferta(
    id_proveedor: UUID,
    categoria: str,
    tipo_red: TipoRed,
    id_partner: UUID | None,
    importe_menor: int,
    moneda: str = "COP",
) -> OfertaCatalogo:
    return OfertaCatalogo(
        id_proveedor=id_proveedor,
        categoria=categoria,
        tipo_red=tipo_red,
        id_partner=id_partner,
        precio=Dinero(importe_menor=importe_menor, moneda=moneda),
    )


def catalogo_laboratorio(version: int = 1) -> CatalogoVigente:
    """Catálogo sintético de 00 §9 (sin duración: esa columna es de la revisión 2)."""
    return CatalogoVigente(
        version=version,
        ofertas=(
            oferta(A101, "plomeria", TipoRed.GENERAL_HDA, None, 15_000_000),
            oferta(A102, "plomeria", TipoRed.GENERAL_HDA, None, 12_000_000),
            oferta(B101, "plomeria", TipoRed.HOMOLOGADA_PARTNER, PARTNER_LAB, 18_000_000),
            oferta(A201, "electricidad", TipoRed.GENERAL_HDA, None, 20_000_000),
            oferta(A301, "cerrajeria", TipoRed.GENERAL_HDA, None, 9_000_000),
        ),
    )


def datos_peticion(**cambios: Any) -> DatosPeticion:
    base = DatosPeticion(
        id_peticion=ID_PETICION,
        id_trabajo=ID_TRABAJO,
        id_solicitud=ID_SOLICITUD,
        id_partner=PARTNER_LAB,
        categoria="plomeria",
        tipo_solicitud=TipoSolicitud.SINIESTRO,
        tipo_red=TipoRed.GENERAL_HDA,
        id_politica=ID_POLITICA,
        version_politica=1,
    )
    return replace(base, **cambios)


def origen_comando(**cambios: Any) -> OrigenComando:
    base = OrigenComando(
        id_comando=ID_COMANDO,
        instante=INSTANTE_COMANDO,
        correlacion=ID_SOLICITUD,
        causacion=CAUSACION,
    )
    return replace(base, **cambios)


def cotizacion_resuelta(
    catalogo: CatalogoVigente | None = None,
    *,
    id: UUID = ID_COTIZACION,
    id_evento: UUID = ID_EVENTO,
    **cambios_peticion: Any,
) -> Cotizacion:
    """Cotización F1 resuelta con el catálogo de laboratorio, con su evento pendiente."""
    return Cotizacion.resolver(
        id=id,
        peticion=datos_peticion(**cambios_peticion),
        origen=origen_comando(),
        catalogo=catalogo or catalogo_laboratorio(),
        id_evento=id_evento,
        instante=INSTANTE_RESULTADO,
    )
