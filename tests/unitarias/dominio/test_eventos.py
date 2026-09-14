from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest

from cotizaciones.modulos.cotizaciones.dominio.eventos import (
    CotizacionRechazada,
    CotizacionRegistrada,
)
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import Dinero, MotivoRechazo

from .datos import (
    A101,
    ID_COMANDO,
    ID_COTIZACION,
    ID_EVENTO,
    ID_SOLICITUD,
    INSTANTE_RESULTADO,
    datos_peticion,
)


def registrada(**cambios: Any) -> CotizacionRegistrada:
    base = CotizacionRegistrada(
        id_evento=ID_EVENTO,
        instante=INSTANTE_RESULTADO,
        id_cotizacion=ID_COTIZACION,
        peticion=datos_peticion(),
        id_comando=ID_COMANDO,
        correlacion=ID_SOLICITUD,
        version_catalogo=1,
        version_cotizacion=1,
        id_proveedor=A101,
        precio=Dinero(importe_menor=15_000_000, moneda="COP"),
    )
    return replace(base, **cambios)


def rechazada(**cambios: Any) -> CotizacionRechazada:
    base = CotizacionRechazada(
        id_evento=ID_EVENTO,
        instante=INSTANTE_RESULTADO,
        id_cotizacion=ID_COTIZACION,
        peticion=datos_peticion(categoria="jardineria"),
        id_comando=ID_COMANDO,
        correlacion=ID_SOLICITUD,
        version_catalogo=1,
        version_cotizacion=1,
        motivo=MotivoRechazo.SIN_OFERTA_PARA_CATEGORIA,
    )
    return replace(base, **cambios)


def test_construccion_valida_de_ambos_hechos() -> None:
    propuesta = registrada()
    assert propuesta.id_proveedor == A101
    assert propuesta.precio.importe_menor == 15_000_000
    rechazo = rechazada()
    assert rechazo.motivo is MotivoRechazo.SIN_OFERTA_PARA_CATEGORIA
    assert not hasattr(rechazo, "precio")
    assert not hasattr(rechazo, "id_proveedor")


COMUNES_INVALIDOS = [
    ("id_evento", UUID(int=0)),
    ("instante", datetime(2026, 9, 12, 15, 0, 4)),
    ("id_cotizacion", UUID(int=0)),
    ("id_comando", None),
    ("correlacion", UUID(int=0)),
    ("peticion", None),
    ("version_catalogo", 0),
    ("version_cotizacion", True),
]


@pytest.mark.parametrize(
    ("campo", "valor"),
    [*COMUNES_INVALIDOS, ("id_proveedor", UUID(int=0)), ("precio", 15_000_000)],
)
def test_registrada_invalida_falla(campo: str, valor: Any) -> None:
    with pytest.raises(ValueError):
        registrada(**{campo: valor})


@pytest.mark.parametrize(
    ("campo", "valor"),
    [*COMUNES_INVALIDOS, ("motivo", "SIN_OFERTA_PARA_CATEGORIA"), ("motivo", None)],
)
def test_rechazada_invalida_falla(campo: str, valor: Any) -> None:
    with pytest.raises(ValueError):
        rechazada(**{campo: valor})


@pytest.mark.parametrize("evento", [registrada(), rechazada()])
def test_los_hechos_son_inmutables(evento: CotizacionRegistrada | CotizacionRechazada) -> None:
    for campo in ("id_evento", "id_cotizacion", "peticion", "version_catalogo"):
        with pytest.raises(FrozenInstanceError):
            setattr(evento, campo, None)


# --- Paso 54 (E3): duracion_estimada_minutos opcional en CotizacionRegistrada ---


def test_registrada_sin_duracion_es_desconocida_por_defecto() -> None:
    assert registrada().duracion_estimada_minutos is None


@pytest.mark.parametrize("duracion", [30, 90, None])
def test_registrada_con_duracion_valida(duracion: int | None) -> None:
    assert registrada(duracion_estimada_minutos=duracion).duracion_estimada_minutos == duracion


@pytest.mark.parametrize("duracion", [0, -1, True, False, 1.5])
def test_registrada_con_duracion_invalida_falla(duracion: Any) -> None:
    with pytest.raises(ValueError, match="duracion"):
        registrada(duracion_estimada_minutos=duracion)
