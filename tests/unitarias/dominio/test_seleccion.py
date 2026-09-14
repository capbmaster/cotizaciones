from typing import Any, cast
from uuid import UUID

import pytest

from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoNoDisponible
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    Dinero,
    EstadoCotizacion,
    MotivoRechazo,
    ResultadoCotizacion,
    TipoRed,
    TipoSolicitud,
)
from cotizaciones.modulos.cotizaciones.dominio.servicios import resolver_oferta

from .datos import (
    A101,
    A102,
    B101,
    PARTNER_LAB,
    PARTNER_SIN_HOMOLOGADOS,
    catalogo_laboratorio,
    datos_peticion,
    oferta,
    uuid_lab,
)

GENERAL = TipoRed.GENERAL_HDA
HOMOLOGADA = TipoRed.HOMOLOGADA_PARTNER
PROPUESTA = EstadoCotizacion.PROPUESTA
RECHAZADA = EstadoCotizacion.RECHAZADA


@pytest.mark.parametrize(
    ("categoria", "red", "partner", "estado", "proveedor", "importe", "motivo"),
    [
        pytest.param("plomeria", GENERAL, PARTNER_LAB, PROPUESTA, A101, 15_000_000, None, id="F1"),
        pytest.param(
            "plomeria", HOMOLOGADA, PARTNER_LAB, PROPUESTA, B101, 18_000_000, None, id="F2"
        ),
        pytest.param(
            "plomeria",
            HOMOLOGADA,
            PARTNER_SIN_HOMOLOGADOS,
            RECHAZADA,
            None,
            None,
            MotivoRechazo.SIN_PROVEEDOR_EN_RED,
            id="F3",
        ),
        pytest.param(
            "electricidad",
            HOMOLOGADA,
            PARTNER_LAB,
            RECHAZADA,
            None,
            None,
            MotivoRechazo.SIN_PROVEEDOR_EN_RED,
            id="F4",
        ),
        pytest.param(
            "jardineria",
            GENERAL,
            PARTNER_LAB,
            RECHAZADA,
            None,
            None,
            MotivoRechazo.SIN_OFERTA_PARA_CATEGORIA,
            id="F5",
        ),
        pytest.param(
            "  Plomeria ", GENERAL, PARTNER_LAB, PROPUESTA, A101, 15_000_000, None, id="F6"
        ),
    ],
)
def test_tabla_de_decisiones(
    categoria: str,
    red: TipoRed,
    partner: UUID,
    estado: EstadoCotizacion,
    proveedor: UUID | None,
    importe: int | None,
    motivo: MotivoRechazo | None,
) -> None:
    peticion = datos_peticion(categoria=categoria, tipo_red=red, id_partner=partner)
    resultado = resolver_oferta(peticion, catalogo_laboratorio())
    assert resultado.estado is estado
    assert resultado.motivo is motivo
    if proveedor is None:
        assert resultado.oferta is None
    else:
        assert resultado.oferta is not None
        assert resultado.oferta.id_proveedor == proveedor
        assert resultado.oferta.precio == Dinero(importe_menor=cast(int, importe), moneda="COP")


def test_empate_elige_el_menor_proveedor_aunque_sea_mas_caro() -> None:
    catalogo = catalogo_laboratorio()
    resultado = resolver_oferta(datos_peticion(), catalogo)
    assert resultado.oferta is not None
    assert resultado.oferta.id_proveedor == A101
    a102 = next(o for o in catalogo.ofertas if o.id_proveedor == A102)
    assert a102.precio.importe_menor < resultado.oferta.precio.importe_menor


def test_la_eleccion_no_depende_del_orden_del_catalogo() -> None:
    invertido = CatalogoVigente(version=1, ofertas=tuple(reversed(catalogo_laboratorio().ofertas)))
    resultado = resolver_oferta(datos_peticion(), invertido)
    assert resultado.oferta is not None
    assert resultado.oferta.id_proveedor == A101


def test_homologada_sin_candidato_no_recurre_a_la_red_general() -> None:
    catalogo = catalogo_laboratorio()
    assert any(o.tipo_red is GENERAL for o in catalogo.ofertas_de_categoria("plomeria"))
    peticion = datos_peticion(tipo_red=HOMOLOGADA, id_partner=PARTNER_SIN_HOMOLOGADOS)
    resultado = resolver_oferta(peticion, catalogo)
    assert resultado.estado is RECHAZADA
    assert resultado.oferta is None


def test_homologada_elige_solo_ofertas_del_partner_de_la_peticion() -> None:
    otro_partner = uuid_lab("0099")
    catalogo = CatalogoVigente(
        version=1,
        ofertas=(
            # b000 ordena antes que b101, pero pertenece a otro partner.
            oferta(uuid_lab("b000"), "plomeria", HOMOLOGADA, otro_partner, 1_000_000),
            oferta(B101, "plomeria", HOMOLOGADA, PARTNER_LAB, 18_000_000),
        ),
    )
    resultado = resolver_oferta(datos_peticion(tipo_red=HOMOLOGADA), catalogo)
    assert resultado.oferta is not None
    assert resultado.oferta.id_proveedor == B101
    assert resultado.oferta.id_partner == PARTNER_LAB


def test_red_general_ignora_las_ofertas_homologadas() -> None:
    catalogo = CatalogoVigente(
        version=1, ofertas=(oferta(B101, "plomeria", HOMOLOGADA, PARTNER_LAB, 18_000_000),)
    )
    resultado = resolver_oferta(datos_peticion(tipo_red=GENERAL), catalogo)
    assert resultado.estado is RECHAZADA
    assert resultado.motivo is MotivoRechazo.SIN_PROVEEDOR_EN_RED


def test_tipo_de_solicitud_no_interviene_en_la_seleccion() -> None:
    catalogo = catalogo_laboratorio()
    siniestro = resolver_oferta(datos_peticion(tipo_solicitud=TipoSolicitud.SINIESTRO), catalogo)
    instalacion = resolver_oferta(
        datos_peticion(tipo_solicitud=TipoSolicitud.INSTALACION), catalogo
    )
    assert siniestro == instalacion


def test_catalogo_ausente_es_error_tecnico() -> None:
    with pytest.raises(CatalogoNoDisponible):
        resolver_oferta(datos_peticion(), None)


def _a101() -> Any:
    return next(o for o in catalogo_laboratorio().ofertas if o.id_proveedor == A101)


def test_resultado_propuesta_exige_oferta_y_ningun_motivo() -> None:
    assert ResultadoCotizacion(estado=PROPUESTA, oferta=_a101()).oferta == _a101()
    with pytest.raises(ValueError, match="propuesta"):
        ResultadoCotizacion(estado=PROPUESTA)
    with pytest.raises(ValueError, match="propuesta"):
        ResultadoCotizacion(
            estado=PROPUESTA, oferta=_a101(), motivo=MotivoRechazo.SIN_PROVEEDOR_EN_RED
        )
    with pytest.raises(ValueError, match="propuesta"):
        ResultadoCotizacion(estado=PROPUESTA, oferta=cast(Any, "a101"))


def test_resultado_rechazado_exige_motivo_y_ninguna_oferta() -> None:
    motivo = MotivoRechazo.SIN_OFERTA_PARA_CATEGORIA
    assert ResultadoCotizacion(estado=RECHAZADA, motivo=motivo).motivo is motivo
    with pytest.raises(ValueError, match="rechazo"):
        ResultadoCotizacion(estado=RECHAZADA)
    with pytest.raises(ValueError, match="rechazo"):
        ResultadoCotizacion(estado=RECHAZADA, oferta=_a101(), motivo=motivo)
    with pytest.raises(ValueError, match="rechazo"):
        ResultadoCotizacion(estado=RECHAZADA, motivo=cast(Any, "SIN_OFERTA_PARA_CATEGORIA"))


def test_resultado_con_estado_invalido_falla() -> None:
    with pytest.raises(ValueError, match="Estado"):
        ResultadoCotizacion(estado=cast(Any, "PROPUESTA"), oferta=_a101())
