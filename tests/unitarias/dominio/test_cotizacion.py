from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest

from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.eventos import (
    CotizacionRechazada,
    CotizacionRegistrada,
)
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoNoDisponible
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    EstadoCotizacion,
    MotivoRechazo,
    OfertaCatalogo,
    ResultadoCotizacion,
    TipoRed,
)

from .datos import (
    A101,
    A201,
    B101,
    ID_COMANDO,
    ID_COTIZACION,
    ID_EVENTO,
    ID_SOLICITUD,
    INSTANTE_RESULTADO,
    PARTNER_LAB,
    PARTNER_SIN_HOMOLOGADOS,
    catalogo_laboratorio,
    datos_peticion,
    oferta,
    origen_comando,
)

GENERAL = TipoRed.GENERAL_HDA
HOMOLOGADA = TipoRed.HOMOLOGADA_PARTNER


def resolver(catalogo_version: int = 1, **cambios_peticion: Any) -> Cotizacion:
    return Cotizacion.resolver(
        id=ID_COTIZACION,
        peticion=datos_peticion(**cambios_peticion),
        origen=origen_comando(),
        catalogo=catalogo_laboratorio(catalogo_version),
        id_evento=ID_EVENTO,
        instante=INSTANTE_RESULTADO,
    )


def propuesta(elegida: OfertaCatalogo) -> ResultadoCotizacion:
    return ResultadoCotizacion(estado=EstadoCotizacion.PROPUESTA, oferta=elegida)


def construir(**cambios: Any) -> Cotizacion:
    base = {
        "id": ID_COTIZACION,
        "peticion": datos_peticion(),
        "origen": origen_comando(),
        "version_catalogo": 1,
        "version_cotizacion": 1,
        "resultado": propuesta(oferta(A101, "plomeria", GENERAL, None, 15_000_000)),
        "resuelta_en": INSTANTE_RESULTADO,
    }
    return Cotizacion(**{**base, **cambios})


@pytest.mark.parametrize(
    ("cambios", "estado", "proveedor", "motivo"),
    [
        pytest.param({}, EstadoCotizacion.PROPUESTA, A101, None, id="F1"),
        pytest.param({"tipo_red": HOMOLOGADA}, EstadoCotizacion.PROPUESTA, B101, None, id="F2"),
        pytest.param(
            {"tipo_red": HOMOLOGADA, "id_partner": PARTNER_SIN_HOMOLOGADOS},
            EstadoCotizacion.RECHAZADA,
            None,
            MotivoRechazo.SIN_PROVEEDOR_EN_RED,
            id="F3",
        ),
        pytest.param(
            {"categoria": "electricidad", "tipo_red": HOMOLOGADA},
            EstadoCotizacion.RECHAZADA,
            None,
            MotivoRechazo.SIN_PROVEEDOR_EN_RED,
            id="F4",
        ),
        pytest.param(
            {"categoria": "jardineria"},
            EstadoCotizacion.RECHAZADA,
            None,
            MotivoRechazo.SIN_OFERTA_PARA_CATEGORIA,
            id="F5",
        ),
    ],
)
def test_resolver_produce_el_estado_y_un_unico_evento(
    cambios: dict[str, Any],
    estado: EstadoCotizacion,
    proveedor: UUID | None,
    motivo: MotivoRechazo | None,
) -> None:
    cotizacion = resolver(**cambios)
    assert cotizacion.estado is estado
    assert cotizacion.version_catalogo == 1
    assert cotizacion.version_cotizacion == 1
    assert cotizacion.resuelta_en == INSTANTE_RESULTADO
    (evento,) = cotizacion.eventos_pendientes
    assert isinstance(evento, CotizacionRegistrada | CotizacionRechazada)
    assert evento.id_evento == ID_EVENTO
    assert evento.instante == INSTANTE_RESULTADO
    assert evento.id_cotizacion == ID_COTIZACION
    assert evento.peticion == cotizacion.peticion
    assert evento.id_comando == ID_COMANDO
    assert evento.correlacion == ID_SOLICITUD
    assert evento.version_catalogo == 1
    assert evento.version_cotizacion == 1
    if proveedor is not None:
        assert isinstance(evento, CotizacionRegistrada)
        assert cotizacion.resultado.oferta is not None
        assert evento.id_proveedor == proveedor
        assert evento.precio == cotizacion.resultado.oferta.precio
    else:
        assert isinstance(evento, CotizacionRechazada)
        assert evento.motivo is motivo
        assert cotizacion.resultado.motivo is motivo


def test_retirar_eventos_deja_el_agregado_sin_pendientes() -> None:
    cotizacion = resolver()
    assert len(cotizacion.retirar_eventos()) == 1
    assert cotizacion.eventos_pendientes == ()


def test_reconstruir_con_el_constructor_no_registra_eventos() -> None:
    original = resolver()
    reconstruida = Cotizacion(
        id=original.id,
        peticion=original.peticion,
        origen=original.origen,
        version_catalogo=original.version_catalogo,
        version_cotizacion=original.version_cotizacion,
        resultado=original.resultado,
        resuelta_en=original.resuelta_en,
    )
    assert reconstruida.eventos_pendientes == ()
    assert reconstruida == original


def test_rechazo_se_reconstruye_sin_eventos() -> None:
    rechazo = ResultadoCotizacion(
        estado=EstadoCotizacion.RECHAZADA, motivo=MotivoRechazo.SIN_OFERTA_PARA_CATEGORIA
    )
    cotizacion = construir(peticion=datos_peticion(categoria="jardineria"), resultado=rechazo)
    assert cotizacion.estado is EstadoCotizacion.RECHAZADA
    assert cotizacion.eventos_pendientes == ()


def test_f6_conserva_la_categoria_tal_como_llego() -> None:
    cotizacion = resolver(categoria="  Plomeria ")
    assert cotizacion.peticion.categoria == "  Plomeria "
    assert cotizacion.resultado.oferta is not None
    assert cotizacion.resultado.oferta.id_proveedor == A101
    (evento,) = cotizacion.eventos_pendientes
    assert isinstance(evento, CotizacionRegistrada)
    assert evento.peticion.categoria == "  Plomeria "


def test_resolver_usa_la_version_del_catalogo_recibido() -> None:
    cotizacion = resolver(catalogo_version=3)
    assert cotizacion.version_catalogo == 3
    (evento,) = cotizacion.eventos_pendientes
    assert isinstance(evento, CotizacionRegistrada)
    assert evento.version_catalogo == 3


def test_resolver_sin_catalogo_es_error_tecnico() -> None:
    with pytest.raises(CatalogoNoDisponible):
        Cotizacion.resolver(
            id=ID_COTIZACION,
            peticion=datos_peticion(),
            origen=origen_comando(),
            catalogo=None,
            id_evento=ID_EVENTO,
            instante=INSTANTE_RESULTADO,
        )


def test_propuesta_de_otro_partner_falla() -> None:
    b101 = oferta(B101, "plomeria", HOMOLOGADA, PARTNER_LAB, 18_000_000)
    peticion = datos_peticion(tipo_red=HOMOLOGADA, id_partner=PARTNER_SIN_HOMOLOGADOS)
    with pytest.raises(ValueError, match="partner"):
        construir(peticion=peticion, resultado=propuesta(b101))


def test_propuesta_de_otra_red_falla() -> None:
    b101 = oferta(B101, "plomeria", HOMOLOGADA, PARTNER_LAB, 18_000_000)
    with pytest.raises(ValueError, match="red"):
        construir(peticion=datos_peticion(tipo_red=GENERAL), resultado=propuesta(b101))


def test_propuesta_de_otra_categoria_falla() -> None:
    a201 = oferta(A201, "electricidad", GENERAL, None, 20_000_000)
    with pytest.raises(ValueError, match="categoria"):
        construir(peticion=datos_peticion(categoria="plomeria"), resultado=propuesta(a201))


def test_correlacion_distinta_de_la_solicitud_falla() -> None:
    with pytest.raises(ValueError, match="correlacion"):
        construir(origen=origen_comando(correlacion=UUID(int=77)))


@pytest.mark.parametrize("version", [0, 2, True])
def test_version_de_cotizacion_distinta_de_uno_falla(version: Any) -> None:
    with pytest.raises(ValueError, match="version"):
        construir(version_cotizacion=version)


def test_version_de_catalogo_invalida_falla() -> None:
    with pytest.raises(ValueError, match="version"):
        construir(version_catalogo=0)


def test_resuelta_en_sin_zona_horaria_falla() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        construir(resuelta_en=datetime(2026, 9, 12, 15, 0, 4))


def test_tipos_invalidos_fallan() -> None:
    with pytest.raises(ValueError):
        construir(peticion=None)
    with pytest.raises(ValueError):
        construir(
            resultado=replace(propuesta(oferta(A101, "plomeria", GENERAL, None, 1)), oferta=None)
        )
