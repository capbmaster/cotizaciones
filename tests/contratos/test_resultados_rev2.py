import io
import json
from pathlib import Path
from typing import Any, cast

import fastavro
from pulsar.schema import AvroSchema

from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.eventos import (
    CotizacionRegistradaV1 as CotizacionRegistradaV1Rev1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v2.eventos import (
    CotizacionRegistradaV1 as CotizacionRegistradaV1Rev2,
)
from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
    mensaje_registrada,
)
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import serializar_evento

from ..unitarias.dominio.datos import cotizacion_resuelta

CONTRATOS = Path(__file__).resolve().parents[2] / "docs" / "contratos"


def cargar(nombre: str) -> Any:
    return json.loads((CONTRATOS / nombre).read_text(encoding="utf-8"))


def test_el_esquema_rev2_es_igual_al_avsc_publicado() -> None:
    assert cargar("cotizacion-registrada-v1.rev2.avsc") == CotizacionRegistradaV1Rev2.schema()


def test_rev2_difiere_de_rev1_solo_en_el_campo_anadido_con_default_null() -> None:
    esquema_v1 = CotizacionRegistradaV1Rev1.schema()
    esquema_v2 = CotizacionRegistradaV1Rev2.schema()
    assert esquema_v1["name"] == esquema_v2["name"] == "CotizacionRegistradaV1"
    assert "namespace" not in esquema_v2
    campos_v1 = esquema_v1["fields"]
    campos_v2 = esquema_v2["fields"]
    assert campos_v2[: len(campos_v1)] == campos_v1
    (nuevo,) = campos_v2[len(campos_v1) :]
    assert nuevo == {
        "name": "duracion_estimada_minutos",
        "default": None,
        "type": ["null", "int"],
    }


def test_las_claves_del_ejemplo_rev2_son_los_campos_en_orden() -> None:
    esquema = cargar("cotizacion-registrada-v1.rev2.avsc")
    ejemplo = cargar("cotizacion-registrada-v1.rev2.ejemplo.json")
    assert list(ejemplo) == [campo["name"] for campo in esquema["fields"]]
    assert ejemplo["version_contrato"] == 2
    assert ejemplo["duracion_estimada_minutos"] == 30


def test_los_bytes_del_ejemplo_rev2_leidos_con_el_avsc_son_el_ejemplo() -> None:
    esquema = cargar("cotizacion-registrada-v1.rev2.avsc")
    ejemplo = cargar("cotizacion-registrada-v1.rev2.ejemplo.json")
    datos = AvroSchema(CotizacionRegistradaV1Rev2).encode(CotizacionRegistradaV1Rev2(**ejemplo))
    assert fastavro.schemaless_reader(io.BytesIO(datos), esquema) == ejemplo
    assert datos == AvroSchema(CotizacionRegistradaV1Rev2).encode(
        CotizacionRegistradaV1Rev2(**ejemplo)
    )


def test_el_fixture_binario_rev2_coincide_con_el_ejemplo() -> None:
    esquema = cargar("cotizacion-registrada-v1.rev2.avsc")
    ejemplo = cargar("cotizacion-registrada-v1.rev2.ejemplo.json")
    datos = (CONTRATOS / "fixtures" / "cotizacion-registrada-v1.rev2.bin").read_bytes()
    assert fastavro.schemaless_reader(io.BytesIO(datos), esquema) == ejemplo


def test_los_bytes_del_mapeador_real_leidos_con_el_avsc_rev2_son_validos() -> None:
    """Desde el Paso 56, mensaje_registrada emite el Record v2 (version_contrato=2)."""
    esquema = cargar("cotizacion-registrada-v1.rev2.avsc")
    (evento,) = cotizacion_resuelta().retirar_eventos()
    documento = serializar_evento(evento)
    mensaje = mensaje_registrada(documento)
    assert isinstance(mensaje, CotizacionRegistradaV1Rev2)
    assert mensaje.version_contrato == 2
    datos = AvroSchema(CotizacionRegistradaV1Rev2).encode(mensaje)
    leido = cast("dict[str, Any]", fastavro.schemaless_reader(io.BytesIO(datos), esquema))
    assert leido["version_contrato"] == 2
    assert leido["duracion_estimada_minutos"] == documento["duracion_estimada_minutos"]
