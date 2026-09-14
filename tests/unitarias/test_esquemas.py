from typing import Any

import pytest

from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.eventos import (
    CotizacionRechazadaV1,
    CotizacionRegistradaV1,
)

COMUNES_RESULTADO = [
    ("event_id", "string"),
    ("tipo", "string"),
    ("version_contrato", "int"),
    ("instante", "string"),
    ("correlacion", "string"),
    ("causacion", "string"),
    ("id_peticion", "string"),
    ("id_trabajo", "string"),
    ("id_solicitud", "string"),
    ("id_partner", "string"),
    ("version_catalogo", "int"),
    ("version_cotizacion", "int"),
]

ESPERADOS: dict[Any, tuple[str, list[tuple[str, str]]]] = {
    SolicitarCotizacionV1: (
        "SolicitarCotizacionV1",
        [
            ("command_id", "string"),
            ("tipo", "string"),
            ("version_contrato", "int"),
            ("instante", "string"),
            ("correlacion", "string"),
            ("causacion", "string"),
            ("id_peticion", "string"),
            ("id_trabajo", "string"),
            ("id_solicitud", "string"),
            ("id_partner", "string"),
            ("categoria", "string"),
            ("tipo_solicitud", "string"),
            ("tipo_red", "string"),
            ("id_politica", "string"),
            ("version_politica", "int"),
        ],
    ),
    CotizacionRegistradaV1: (
        "CotizacionRegistradaV1",
        [
            *COMUNES_RESULTADO,
            ("id_cotizacion", "string"),
            ("id_proveedor", "string"),
            ("importe_menor", "long"),
            ("moneda", "string"),
            ("categoria", "string"),
            ("tipo_red", "string"),
        ],
    ),
    CotizacionRechazadaV1: (
        "CotizacionRechazadaV1",
        [*COMUNES_RESULTADO, ("motivo", "string")],
    ),
}


@pytest.mark.parametrize("record", list(ESPERADOS), ids=lambda r: r.__name__)
def test_nombre_orden_y_tipos_del_esquema(record: Any) -> None:
    nombre, campos = ESPERADOS[record]
    esquema = record.schema()
    assert esquema["type"] == "record"
    assert esquema["name"] == nombre
    assert "namespace" not in esquema
    assert [(campo["name"], campo["type"]) for campo in esquema["fields"]] == campos
    assert all("default" not in campo for campo in esquema["fields"])


def test_cantidad_de_campos_de_cada_contrato() -> None:
    assert len(SolicitarCotizacionV1.schema()["fields"]) == 15
    assert len(CotizacionRegistradaV1.schema()["fields"]) == 18
    assert len(CotizacionRechazadaV1.schema()["fields"]) == 13
