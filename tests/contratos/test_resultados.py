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


# El registro v1 sigue congelado (00 §5) y sus .avsc/.ejemplo.json no cambian, pero desde el
# Paso 56 el escritor real (mensaje_registrada) publica el Record v2: su ida y vuelta con el
# mapeador se prueba en test_resultados_rev2.py, no aqui.
CASOS_ESQUEMA = [
    pytest.param("cotizacion-registrada-v1", CotizacionRegistradaV1, id="registrada"),
    pytest.param("cotizacion-rechazada-v1", CotizacionRechazadaV1, id="rechazada"),
]

CASOS = [
    pytest.param(
        "cotizacion-rechazada-v1",
        CotizacionRechazadaV1,
        mensaje_rechazada,
        documento_rechazo,
        id="rechazada",
    ),
]


@pytest.mark.parametrize(("nombre", "record"), CASOS_ESQUEMA)
def test_el_esquema_del_record_es_el_avsc_publicado(nombre: str, record: Any) -> None:
    assert cargar(f"{nombre}.avsc") == record.schema()


@pytest.mark.parametrize(("nombre", "record"), CASOS_ESQUEMA)
def test_las_claves_del_ejemplo_son_los_campos_en_orden(nombre: str, record: Any) -> None:
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
    esperados = {
        f"{nombre}.{extension}"
        for nombre in (
            "solicitar-cotizacion-v1",
            "cotizacion-registrada-v1",
            "cotizacion-rechazada-v1",
        )
        for extension in ("avsc", "ejemplo.json")
    }
    esperados |= {
        "cotizacion-registrada-v1.rev2.avsc",
        "cotizacion-registrada-v1.rev2.ejemplo.json",
        "fixtures/cotizacion-registrada-v1.bin",
        "fixtures/cotizacion-registrada-v1.rev2.bin",
    }
    assert set(publicados) == esperados
    for archivo, esperado in publicados.items():
        assert hashlib.sha256((CONTRATOS / archivo).read_bytes()).hexdigest() == esperado, archivo


def test_los_tres_contratos_tienen_nombres_de_record_distintos() -> None:
    nombres = {
        r.schema()["name"]
        for r in (SolicitarCotizacionV1, CotizacionRegistradaV1, CotizacionRechazadaV1)
    }
    assert nombres == {"SolicitarCotizacionV1", "CotizacionRegistradaV1", "CotizacionRechazadaV1"}
