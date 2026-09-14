import hashlib
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import fastavro
import pytest
from pulsar.schema import AvroSchema

from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.eventos import (
    CotizacionRechazadaV1,
    CotizacionRegistradaV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
    mensaje_rechazada,
    mensaje_registrada,
)
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import serializar_evento
from cotizaciones.seedwork.infraestructura.serializacion import Documento

from ..unitarias.dominio.datos import cotizacion_resuelta, uuid_lab

CONTRATOS = Path(__file__).resolve().parents[2] / "docs" / "contratos"


def cargar(nombre: str) -> Any:
    return json.loads((CONTRATOS / nombre).read_text(encoding="utf-8"))


def documento_propuesta() -> Documento:
    (evento,) = cotizacion_resuelta().retirar_eventos()
    return serializar_evento(evento)


def documento_rechazo() -> Documento:
    (evento,) = cotizacion_resuelta(
        categoria="jardineria", id_evento=uuid_lab("0032")
    ).retirar_eventos()
    return serializar_evento(evento)


CASOS = [
    pytest.param(
        "cotizacion-registrada-v1",
        CotizacionRegistradaV1,
        mensaje_registrada,
        documento_propuesta,
        id="registrada",
    ),
    pytest.param(
        "cotizacion-rechazada-v1",
        CotizacionRechazadaV1,
        mensaje_rechazada,
        documento_rechazo,
        id="rechazada",
    ),
]


@pytest.mark.parametrize(("nombre", "record", "mapear", "documento"), CASOS)
def test_el_esquema_del_record_es_el_avsc_publicado(
    nombre: str, record: Any, mapear: Callable[[Documento], Any], documento: Callable[[], Documento]
) -> None:
    assert cargar(f"{nombre}.avsc") == record.schema()


@pytest.mark.parametrize(("nombre", "record", "mapear", "documento"), CASOS)
def test_las_claves_del_ejemplo_son_los_campos_en_orden(
    nombre: str, record: Any, mapear: Callable[[Documento], Any], documento: Callable[[], Documento]
) -> None:
    campos = [campo["name"] for campo in cargar(f"{nombre}.avsc")["fields"]]
    assert list(cargar(f"{nombre}.ejemplo.json")) == campos


@pytest.mark.parametrize(("nombre", "record", "mapear", "documento"), CASOS)
def test_los_bytes_del_mapeador_leidos_con_el_avsc_son_el_ejemplo(
    nombre: str, record: Any, mapear: Callable[[Documento], Any], documento: Callable[[], Documento]
) -> None:
    esquema = AvroSchema(record)
    datos = esquema.encode(mapear(documento()))
    leido = fastavro.schemaless_reader(io.BytesIO(datos), cargar(f"{nombre}.avsc"))
    assert leido == cargar(f"{nombre}.ejemplo.json")
    assert datos == esquema.encode(mapear(documento()))


def test_los_checksums_publicados_coinciden_con_los_archivos() -> None:
    publicados: dict[str, str] = {}
    for linea in (CONTRATOS / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        if linea.strip():
            esperado, archivo = linea.split(maxsplit=1)
            publicados[archivo] = esperado
    assert set(publicados) == {
        f"{nombre}.{extension}"
        for nombre in (
            "solicitar-cotizacion-v1",
            "cotizacion-registrada-v1",
            "cotizacion-rechazada-v1",
        )
        for extension in ("avsc", "ejemplo.json")
    }
    for archivo, esperado in publicados.items():
        assert hashlib.sha256((CONTRATOS / archivo).read_bytes()).hexdigest() == esperado, archivo


def test_los_tres_contratos_tienen_nombres_de_record_distintos() -> None:
    nombres = {
        r.schema()["name"]
        for r in (SolicitarCotizacionV1, CotizacionRegistradaV1, CotizacionRechazadaV1)
    }
    assert nombres == {"SolicitarCotizacionV1", "CotizacionRegistradaV1", "CotizacionRechazadaV1"}
