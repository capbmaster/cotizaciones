import io
import json
from pathlib import Path
from typing import Any

import fastavro
from pulsar.schema import AvroSchema

from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
    comando_desde_mensaje,
)

from ..unitarias.aplicacion.datos import comando_peticion

CONTRATOS = Path(__file__).resolve().parents[2] / "docs" / "contratos"
AVSC = "solicitar-cotizacion-v1.avsc"
EJEMPLO = "solicitar-cotizacion-v1.ejemplo.json"


def cargar(nombre: str) -> Any:
    return json.loads((CONTRATOS / nombre).read_text(encoding="utf-8"))


def test_el_esquema_del_record_es_el_avsc_publicado() -> None:
    assert cargar(AVSC) == SolicitarCotizacionV1.schema()


def test_las_claves_del_ejemplo_son_los_campos_en_orden() -> None:
    assert list(cargar(EJEMPLO)) == [campo["name"] for campo in cargar(AVSC)["fields"]]


def test_los_bytes_leidos_con_el_avsc_son_el_ejemplo_y_son_deterministas() -> None:
    ejemplo = cargar(EJEMPLO)
    esquema = AvroSchema(SolicitarCotizacionV1)
    datos = esquema.encode(SolicitarCotizacionV1(**ejemplo))
    assert fastavro.schemaless_reader(io.BytesIO(datos), cargar(AVSC)) == ejemplo
    assert datos == esquema.encode(SolicitarCotizacionV1(**ejemplo))


def test_el_ejemplo_se_traduce_al_comando_propio_de_la_f1() -> None:
    assert comando_desde_mensaje(SolicitarCotizacionV1(**cargar(EJEMPLO))) == comando_peticion()
