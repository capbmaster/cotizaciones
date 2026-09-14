"""Compatibilidad de esquema contra un broker real, en un topico de control aislado (Paso 57).

No comparte topicos con `pulsar.py` (que usa `prueba-*`): usa `compat-*` y limpia el topico al
terminar. Objetivo de CI: < 60 s (ver .github/workflows/ci.yml, job `compatibilidad`).
"""

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pulsar
import pytest
from pulsar.schema import Integer, Long, Record, String

from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.eventos import (
    CotizacionRegistradaV1 as CotizacionRegistradaV1Rev1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v2.eventos import (
    CotizacionRegistradaV1 as CotizacionRegistradaV1Rev2,
)

from .pulsar import URL_ADMIN, URL_PULSAR, _admin, eliminar_topico


class ImporteComoTexto(Record):  # type: ignore[misc]
    """Cambio incompatible: retipa `importe_menor` de long a string (00 §9, Paso 57)."""

    event_id = String(required=True)
    tipo = String(required=True)
    version_contrato = Integer(required=True)
    instante = String(required=True)
    correlacion = String(required=True)
    causacion = String(required=True)
    id_peticion = String(required=True)
    id_trabajo = String(required=True)
    id_solicitud = String(required=True)
    id_partner = String(required=True)
    version_catalogo = Integer(required=True)
    version_cotizacion = Integer(required=True)
    id_cotizacion = String(required=True)
    id_proveedor = String(required=True)
    importe_menor = String(required=True)
    moneda = String(required=True)
    categoria = String(required=True)
    tipo_red = String(required=True)
    duracion_estimada_minutos = Integer(default=None, required_default=True)


class CampoObligatorioSinDefault(Record):  # type: ignore[misc]
    """Otro cambio incompatible: campo nuevo obligatorio, sin default (00 §9, Paso 57)."""

    event_id = String(required=True)
    tipo = String(required=True)
    version_contrato = Integer(required=True)
    instante = String(required=True)
    correlacion = String(required=True)
    causacion = String(required=True)
    id_peticion = String(required=True)
    id_trabajo = String(required=True)
    id_solicitud = String(required=True)
    id_partner = String(required=True)
    version_catalogo = Integer(required=True)
    version_cotizacion = Integer(required=True)
    id_cotizacion = String(required=True)
    id_proveedor = String(required=True)
    importe_menor = Long(required=True)
    moneda = String(required=True)
    categoria = String(required=True)
    tipo_red = String(required=True)
    duracion_estimada_minutos = Integer(default=None, required_default=True)
    zona_horaria = String(required=True)


def _establecer_compatibilidad(topico: str, estrategia: str) -> None:
    ruta = f"{topico.replace('://', '/')}/schemaCompatibilityStrategy"
    _peticion("PUT", ruta, json.dumps(estrategia).encode())


def _peticion(metodo: str, ruta: str, cuerpo: bytes | None) -> None:
    import urllib.request

    peticion = urllib.request.Request(
        f"{URL_ADMIN}/admin/v2/{ruta}",
        data=cuerpo,
        method=metodo,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=10) as respuesta:
        respuesta.read()


@pytest.fixture
def topico_control() -> Iterator[str]:
    topico = f"persistent://public/default/compat-registrada-{uuid4().hex[:12]}"
    try:
        _admin("GET", "clusters")
    except Exception:
        pytest.fail(
            "Pulsar requerido: docker compose up -d --wait pulsar "
            "(COTIZACIONES_TEST_PULSAR_URL / COTIZACIONES_TEST_PULSAR_ADMIN_URL)",
            pytrace=False,
        )
    try:
        yield topico
    finally:
        eliminar_topico(topico)


def test_full_transitive_acepta_v2_y_rechaza_cambios_incompatibles(topico_control: str) -> None:
    cliente = pulsar.Client(URL_PULSAR, operation_timeout_seconds=5, connection_timeout_ms=3000)
    try:
        from pulsar.schema import AvroSchema

        # Se registra v1 primero (congelado): mismo orden que preparar_pulsar.py.
        cliente.create_producer(
            topico_control, schema=AvroSchema(CotizacionRegistradaV1Rev1)
        ).close()
        _establecer_compatibilidad(topico_control, "FULL_TRANSITIVE")

        # v2 es aditivo (campo nuevo con default null): se acepta.
        cliente.create_producer(
            topico_control, schema=AvroSchema(CotizacionRegistradaV1Rev2)
        ).close()

        # Retipar un campo existente rompe la compatibilidad: se rechaza.
        with pytest.raises(pulsar.PulsarException, match="IncompatibleSchema"):
            cliente.create_producer(topico_control, schema=AvroSchema(ImporteComoTexto)).close()

        # Un campo nuevo obligatorio sin default tampoco es compatible: se rechaza.
        with pytest.raises(pulsar.PulsarException, match="IncompatibleSchema"):
            cliente.create_producer(
                topico_control, schema=AvroSchema(CampoObligatorioSinDefault)
            ).close()
    finally:
        cliente.close()


def test_lector_v1_congelado_sigue_consumiendo_mensajes_v2(topico_control: str) -> None:
    """El fullname del Record no cambio (00 §9): un consumidor con el esquema v1 lee mensajes
    escritos con v2 e ignora el campo nuevo, sin error de deserializacion."""
    from pulsar.schema import AvroSchema

    cliente = pulsar.Client(URL_PULSAR, operation_timeout_seconds=5, connection_timeout_ms=3000)
    try:
        cliente.create_producer(
            topico_control, schema=AvroSchema(CotizacionRegistradaV1Rev1)
        ).close()
        _establecer_compatibilidad(topico_control, "FULL_TRANSITIVE")

        productor_v2 = cliente.create_producer(
            topico_control,
            schema=AvroSchema(CotizacionRegistradaV1Rev2),
            send_timeout_millis=5000,
        )
        mensaje_v2 = CotizacionRegistradaV1Rev2(
            event_id=str(uuid4()),
            tipo="CotizacionRegistrada.v1",
            version_contrato=2,
            instante="2026-09-14T00:00:00+00:00",
            correlacion=str(uuid4()),
            causacion=str(uuid4()),
            id_peticion=str(uuid4()),
            id_trabajo=str(uuid4()),
            id_solicitud=str(uuid4()),
            id_partner=str(uuid4()),
            version_catalogo=2,
            version_cotizacion=1,
            id_cotizacion=str(uuid4()),
            id_proveedor=str(uuid4()),
            importe_menor=15_000_000,
            moneda="COP",
            categoria="plomeria",
            tipo_red="GENERAL_HDA",
            duracion_estimada_minutos=30,
        )
        productor_v2.send(mensaje_v2)
        productor_v2.close()

        consumidor_v1 = cliente.subscribe(
            topico_control,
            "lector-v1-congelado",
            schema=AvroSchema(CotizacionRegistradaV1Rev1),
            consumer_type=pulsar.ConsumerType.Shared,
            initial_position=pulsar.InitialPosition.Earliest,
        )
        try:
            recibido: Any = consumidor_v1.receive(timeout_millis=5000).value()
            assert recibido.id_cotizacion == mensaje_v2.id_cotizacion
            assert recibido.importe_menor == 15_000_000
            assert not hasattr(recibido, "duracion_estimada_minutos")
        finally:
            consumidor_v1.close()
    finally:
        cliente.close()
