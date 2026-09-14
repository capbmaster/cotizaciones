from typing import Any, cast
from uuid import UUID

import pytest

from cotizaciones.modulos.cotizaciones.dominio.excepciones import (
    CatalogoInvalido,
    CatalogoNoDisponible,
    ErrorCatalogo,
)
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    OfertaCatalogo,
    TipoRed,
)

from .datos import A101, A102, A201, B101, PARTNER_LAB, catalogo_laboratorio, oferta


def test_errores_de_catalogo_son_tecnicos_y_no_errores_de_validacion() -> None:
    for error in (CatalogoNoDisponible, CatalogoInvalido):
        assert issubclass(error, ErrorCatalogo)
        assert not issubclass(error, ValueError)


def test_ofertas_validas_de_cada_red() -> None:
    general = oferta(A101, "plomeria", TipoRed.GENERAL_HDA, None, 15_000_000)
    homologada = oferta(B101, "plomeria", TipoRed.HOMOLOGADA_PARTNER, PARTNER_LAB, 18_000_000)
    assert general.id_partner is None
    assert homologada.id_partner == PARTNER_LAB


def test_oferta_general_con_partner_falla() -> None:
    with pytest.raises(CatalogoInvalido, match="general"):
        oferta(A101, "plomeria", TipoRed.GENERAL_HDA, PARTNER_LAB, 15_000_000)


def test_oferta_homologada_sin_partner_falla() -> None:
    with pytest.raises(CatalogoInvalido, match="homologada"):
        oferta(B101, "plomeria", TipoRed.HOMOLOGADA_PARTNER, None, 18_000_000)


@pytest.mark.parametrize("categoria", ["Plomeria", " plomeria", "plomeria ", "", "   "])
def test_oferta_con_categoria_sin_normalizar_falla(categoria: str) -> None:
    with pytest.raises(CatalogoInvalido, match="categoria"):
        oferta(A101, categoria, TipoRed.GENERAL_HDA, None, 15_000_000)


def test_oferta_con_proveedor_nulo_o_red_invalida_falla() -> None:
    with pytest.raises(CatalogoInvalido):
        oferta(UUID(int=0), "plomeria", TipoRed.GENERAL_HDA, None, 15_000_000)
    with pytest.raises(CatalogoInvalido):
        oferta(A101, "plomeria", cast(TipoRed, "GENERAL_HDA"), None, 15_000_000)


def test_oferta_con_precio_que_no_es_dinero_falla() -> None:
    with pytest.raises(CatalogoInvalido, match="precio"):
        OfertaCatalogo(
            id_proveedor=A101,
            categoria="plomeria",
            tipo_red=TipoRed.GENERAL_HDA,
            id_partner=None,
            precio=cast(Any, 15_000_000),
        )


def test_catalogo_sin_ofertas_falla() -> None:
    with pytest.raises(CatalogoInvalido, match="oferta"):
        CatalogoVigente(version=1, ofertas=())


def test_catalogo_con_ofertas_en_lista_falla() -> None:
    with pytest.raises(CatalogoInvalido):
        CatalogoVigente(version=1, ofertas=cast(Any, list(catalogo_laboratorio().ofertas)))


def test_catalogo_con_combinacion_duplicada_falla_aunque_cambie_el_precio() -> None:
    primera = oferta(A101, "plomeria", TipoRed.GENERAL_HDA, None, 15_000_000)
    misma_combinacion = oferta(A101, "plomeria", TipoRed.GENERAL_HDA, None, 99_000_000)
    with pytest.raises(CatalogoInvalido, match="duplicada"):
        CatalogoVigente(version=1, ofertas=(primera, misma_combinacion))


@pytest.mark.parametrize("version", [0, -1, True])
def test_catalogo_con_version_invalida_falla(version: Any) -> None:
    with pytest.raises(CatalogoInvalido, match="version"):
        CatalogoVigente(version=version, ofertas=catalogo_laboratorio().ofertas)


def test_mismo_proveedor_en_otra_categoria_es_valido() -> None:
    catalogo = CatalogoVigente(
        version=1,
        ofertas=(
            oferta(A101, "plomeria", TipoRed.GENERAL_HDA, None, 15_000_000),
            oferta(A101, "electricidad", TipoRed.GENERAL_HDA, None, 20_000_000),
        ),
    )
    assert len(catalogo.ofertas) == 2


def test_catalogo_de_laboratorio() -> None:
    catalogo = catalogo_laboratorio()
    assert catalogo.version == 1
    assert len(catalogo.ofertas) == 5
    assert {o.precio.moneda for o in catalogo.ofertas} == {"COP"}


def test_ofertas_de_categoria_filtra_por_clave_exacta() -> None:
    catalogo = catalogo_laboratorio()
    plomeria = catalogo.ofertas_de_categoria("plomeria")
    assert {o.id_proveedor for o in plomeria} == {A101, A102, B101}
    assert [o.id_proveedor for o in catalogo.ofertas_de_categoria("electricidad")] == [A201]
    assert catalogo.ofertas_de_categoria("Plomeria") == ()
    assert catalogo.ofertas_de_categoria("jardineria") == ()
