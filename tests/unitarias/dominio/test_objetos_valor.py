from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    Dinero,
    TipoRed,
    TipoSolicitud,
    normalizar_categoria,
)

from .datos import ID_SOLICITUD, datos_peticion, origen_comando


@pytest.mark.parametrize(
    "importe", [0, -1, True, False, 1.5, 15_000_000.0, Decimal("150000.00"), "15000000", None]
)
def test_importe_invalido_falla(importe: Any) -> None:
    with pytest.raises(ValueError, match="importe"):
        Dinero(importe_menor=importe, moneda="COP")


def test_dinero_conserva_el_entero_exacto_y_compara_por_valor() -> None:
    precio = Dinero(importe_menor=15_000_000, moneda="COP")
    assert type(precio.importe_menor) is int
    assert precio.importe_menor == 15_000_000
    assert precio == Dinero(importe_menor=15_000_000, moneda="COP")
    assert precio != Dinero(importe_menor=15_000_001, moneda="COP")


@pytest.mark.parametrize("moneda", ["cop", "COPX", "CO", "", "C0P", " COP", 123, None])
def test_moneda_invalida_falla(moneda: Any) -> None:
    with pytest.raises(ValueError, match="moneda"):
        Dinero(importe_menor=15_000_000, moneda=moneda)


@pytest.mark.parametrize(
    ("texto", "clave"),
    [("  Plomeria ", "plomeria"), ("plomeria", "plomeria"), ("ELECTRICIDAD", "electricidad")],
)
def test_normalizar_categoria(texto: str, clave: str) -> None:
    assert normalizar_categoria(texto) == clave


@pytest.mark.parametrize("texto", ["", "   ", "\t\n"])
def test_normalizar_categoria_sin_caracteres_visibles_falla(texto: str) -> None:
    with pytest.raises(ValueError, match="categoria"):
        normalizar_categoria(texto)


def test_la_peticion_conserva_la_categoria_y_expone_su_clave() -> None:
    peticion = datos_peticion(categoria="  Plomeria ")
    assert peticion.categoria == "  Plomeria "
    assert peticion.clave_categoria == "plomeria"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("tipo_red", "GENERAL_HDA"),
        ("tipo_red", "OTRA_RED"),
        ("tipo_solicitud", "SINIESTRO"),
        ("tipo_solicitud", None),
    ],
)
def test_peticion_con_enumeracion_invalida_falla(campo: str, valor: Any) -> None:
    with pytest.raises(ValueError):
        datos_peticion(**{campo: valor})


@pytest.mark.parametrize(
    "campo", ["id_peticion", "id_trabajo", "id_solicitud", "id_partner", "id_politica"]
)
def test_peticion_con_identidad_nula_falla(campo: str) -> None:
    with pytest.raises(ValueError, match="UUID"):
        datos_peticion(**{campo: UUID(int=0)})


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("categoria", ""), ("categoria", "   "), ("version_politica", 0), ("version_politica", True)],
)
def test_peticion_con_texto_o_version_invalidos_falla(campo: str, valor: Any) -> None:
    with pytest.raises(ValueError):
        datos_peticion(**{campo: valor})


def test_peticiones_iguales_campo_a_campo_son_la_misma() -> None:
    assert datos_peticion() == datos_peticion()
    assert hash(datos_peticion()) == hash(datos_peticion())


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("id_peticion", UUID(int=100)),
        ("id_trabajo", UUID(int=101)),
        ("id_solicitud", UUID(int=102)),
        ("id_partner", UUID(int=103)),
        ("categoria", "electricidad"),
        ("categoria", " plomeria"),
        ("tipo_solicitud", TipoSolicitud.INSTALACION),
        ("tipo_red", TipoRed.HOMOLOGADA_PARTNER),
        ("id_politica", UUID(int=104)),
        ("version_politica", 2),
    ],
)
def test_peticiones_difieren_si_cambia_cualquier_campo(campo: str, valor: Any) -> None:
    assert datos_peticion(**{campo: valor}) != datos_peticion()


def test_origen_del_comando_valido() -> None:
    origen = origen_comando()
    assert origen.correlacion == ID_SOLICITUD


@pytest.mark.parametrize("campo", ["id_comando", "correlacion", "causacion"])
def test_origen_con_identidad_nula_falla(campo: str) -> None:
    with pytest.raises(ValueError, match="UUID"):
        origen_comando(**{campo: UUID(int=0)})


def test_origen_exige_instante_con_zona_horaria() -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        origen_comando(instante=datetime(2026, 9, 12, 15, 0, 3))
