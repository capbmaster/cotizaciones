"""Compatibilidad de esquema sin red (00 §9, Paso 57): solo fastavro y los fixtures binarios.

Verifica en ambas direcciones que el Record v2 (con `duracion_estimada_minutos`, default null)
es compatible hacia atras y hacia adelante con el v1 congelado, usando los mismos bytes que
`docs/contratos/CONGELACION-v1.md` declara como frozen.
"""

import io
import json
from pathlib import Path
from typing import Any, cast

import fastavro

CONTRATOS = Path(__file__).resolve().parents[2] / "docs" / "contratos"


def _cargar(nombre: str) -> Any:
    return json.loads((CONTRATOS / nombre).read_text(encoding="utf-8"))


def _leer(fixture: str, esquema_escritor: str, esquema_lector: str) -> dict[str, Any]:
    datos = (CONTRATOS / "fixtures" / fixture).read_bytes()
    leido = fastavro.schemaless_reader(
        io.BytesIO(datos), _cargar(esquema_escritor), _cargar(esquema_lector)
    )
    return cast("dict[str, Any]", leido)


def test_escritor_v1_leido_con_esquema_v2_da_duracion_nula() -> None:
    leido = _leer(
        "cotizacion-registrada-v1.bin",
        "cotizacion-registrada-v1.avsc",
        "cotizacion-registrada-v1.rev2.avsc",
    )
    esperado = _cargar("cotizacion-registrada-v1.ejemplo.json")
    assert leido["duracion_estimada_minutos"] is None
    for campo, valor in esperado.items():
        assert leido[campo] == valor


def test_escritor_v2_leido_con_esquema_v1_ignora_el_campo_anadido() -> None:
    leido = _leer(
        "cotizacion-registrada-v1.rev2.bin",
        "cotizacion-registrada-v1.rev2.avsc",
        "cotizacion-registrada-v1.avsc",
    )
    esperado = _cargar("cotizacion-registrada-v1.rev2.ejemplo.json")
    assert "duracion_estimada_minutos" not in leido
    campos_v1 = [campo["name"] for campo in _cargar("cotizacion-registrada-v1.avsc")["fields"]]
    assert set(leido) == set(campos_v1)
    for campo in campos_v1:
        assert leido[campo] == esperado[campo]


def test_ambos_fixtures_declaran_version_contrato_coherente() -> None:
    assert _cargar("cotizacion-registrada-v1.ejemplo.json")["version_contrato"] == 1
    assert _cargar("cotizacion-registrada-v1.rev2.ejemplo.json")["version_contrato"] == 2
