import pytest

from cotizaciones.config.rutas import (
    DESTINO_RECHAZADA,
    DESTINO_REGISTRADA,
    DESTINOS_ADMITIDOS,
    destinos_evento,
)
from cotizaciones.seedwork.dominio.eventos import EventoDominio

from .dominio.datos import ID_EVENTO, INSTANTE_RESULTADO, cotizacion_resuelta


def test_nombres_internos_de_la_seccion_7() -> None:
    assert DESTINO_REGISTRADA == "integracion.cotizacion_registrada.v1"
    assert DESTINO_RECHAZADA == "integracion.cotizacion_rechazada.v1"
    assert DESTINOS_ADMITIDOS == (DESTINO_REGISTRADA, DESTINO_RECHAZADA)


def test_cada_resultado_tiene_un_unico_destino() -> None:
    (propuesta,) = cotizacion_resuelta().retirar_eventos()
    (rechazo,) = cotizacion_resuelta(categoria="jardineria").retirar_eventos()
    assert destinos_evento(propuesta) == (DESTINO_REGISTRADA,)
    assert destinos_evento(rechazo) == (DESTINO_RECHAZADA,)


def test_evento_sin_ruta_falla() -> None:
    with pytest.raises(ValueError, match="ruta"):
        destinos_evento(EventoDominio(id_evento=ID_EVENTO, instante=INSTANTE_RESULTADO))
