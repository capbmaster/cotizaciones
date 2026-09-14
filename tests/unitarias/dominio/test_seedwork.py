from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from cotizaciones.seedwork.dominio.entidades import AgregacionRaiz, Entidad
from cotizaciones.seedwork.dominio.eventos import EventoDominio
from cotizaciones.seedwork.dominio.validaciones import (
    validar_instante,
    validar_texto,
    validar_version,
)

INSTANTE = datetime(2026, 9, 12, 15, 0, 3, tzinfo=UTC)


class OtraEntidad(Entidad):
    pass


def test_entidades_se_comparan_por_tipo_e_identidad() -> None:
    primera = Entidad(id=UUID(int=1))
    assert primera == Entidad(id=UUID(int=1))
    assert hash(primera) == hash(Entidad(id=UUID(int=1)))
    assert primera != Entidad(id=UUID(int=2))
    assert primera != OtraEntidad(id=UUID(int=1))


def test_retirar_eventos_devuelve_y_vacia_los_pendientes() -> None:
    raiz = AgregacionRaiz(id=UUID(int=1))
    evento = EventoDominio(id_evento=UUID(int=10), instante=INSTANTE)
    raiz._registrar_evento(evento)
    assert raiz.eventos_pendientes == (evento,)
    assert raiz.retirar_eventos() == (evento,)
    assert len(raiz.eventos_pendientes) == 0
    assert len(raiz.retirar_eventos()) == 0


@pytest.mark.parametrize(
    "identidad", ["", 123, None, UUID(int=0), "00000000-0000-0000-0000-000000000001"]
)
def test_identidad_invalida_se_rechaza(identidad: Any) -> None:
    with pytest.raises(ValueError, match="UUID"):
        Entidad(id=identidad)


def test_evento_exige_identidad_no_nula_e_instante_con_zona() -> None:
    with pytest.raises(ValueError, match="UUID"):
        EventoDominio(id_evento=UUID(int=0), instante=INSTANTE)
    with pytest.raises(ValueError, match="zona horaria"):
        EventoDominio(id_evento=UUID(int=10), instante=datetime(2026, 9, 12, 15, 0, 3))
    assert EventoDominio(id_evento=UUID(int=10), instante=INSTANTE).instante == INSTANTE


@pytest.mark.parametrize("instante", [datetime(2026, 9, 12), "2026-09-12T15:00:03+00:00", None])
def test_instante_invalido_se_rechaza(instante: Any) -> None:
    with pytest.raises(ValueError, match="zona horaria"):
        validar_instante(instante)


@pytest.mark.parametrize("version", [0, -1, True, False, 1.0, "1", None])
def test_version_invalida_se_rechaza(version: Any) -> None:
    with pytest.raises(ValueError, match="version"):
        validar_version(version)


def test_version_entera_positiva_es_valida() -> None:
    validar_version(1)
    validar_version(7)


@pytest.mark.parametrize("texto", ["", "   ", "\t\n", None, 5])
def test_texto_sin_caracteres_visibles_se_rechaza(texto: Any) -> None:
    with pytest.raises(ValueError, match="caracter visible"):
        validar_texto(texto)
