"""Smoke de despliegue (Paso 62): verifica una imagen ya corriendo, sin conocer su codigo fuente.

Comprueba salud, envia F1 y F5 con el doble de Orquestacion (por Pulsar, nunca por HTTP) y
confirma por HTTP que ambos resultados quedaron persistidos. Termina con codigo distinto de
cero ante cualquier fallo.

NOTA de plataforma: el cliente nativo (C++) de pulsar-client aborta el proceso al cerrarse
bajo emulacion QEMU (Apple Silicon ejecutando linux/amd64, como esta imagen). Por eso este
script nunca cierra el cliente explicitamente y termina siempre con os._exit(), que evita la
finalizacion normal del interprete (y con ella, el destructor del cliente). En Cloud Run
(amd64 nativo) esto no ocurre, pero el patron es inofensivo ahi tambien.
"""

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

PLAZO_CONSULTA_S = 30
ESPERA_LISTO_S = 30
PARTNER_LAB = UUID("00000000-0000-0000-0000-000000000002")
POLITICA_LAB = UUID("00000000-0000-0000-0000-000000000003")


def _get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as respuesta:
            return respuesta.status, respuesta.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()
    except urllib.error.URLError as error:
        return 0, str(error)


def comprobar_salud(api_url: str) -> str | None:
    estado, cuerpo = _get(f"{api_url}/health/live")
    if estado != 200:
        return f"/health/live respondio {estado}: {cuerpo}"
    print(f"OK: /health/live -> {estado}")

    limite = time.monotonic() + ESPERA_LISTO_S
    while time.monotonic() < limite:
        estado, cuerpo = _get(f"{api_url}/health/ready")
        if estado == 200:
            print(f"OK: /health/ready -> {estado} {cuerpo}")
            return None
        time.sleep(1)
    return f"/health/ready nunca respondio 200 (ultimo: {estado} {cuerpo})"


def enviar_doble(cliente: Any, topico: str, categoria: str, red: str, id_peticion: str) -> None:
    """Publica SolicitarCotizacion.v1 (mismo rol que scripts/enviar_peticion.py, en el proceso
    del smoke para reutilizar un unico cliente que nunca se cierra; ver nota de modulo)."""
    from pulsar.schema import AvroSchema

    from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
        SolicitarCotizacionV1,
    )

    productor = cliente.create_producer(topico, schema=AvroSchema(SolicitarCotizacionV1))
    id_solicitud = str(uuid4())
    id_trabajo = str(uuid4())
    command_id = str(uuid4())
    mensaje = SolicitarCotizacionV1(
        command_id=command_id,
        tipo="SolicitarCotizacion.v1",
        version_contrato=1,
        instante=datetime.now(UTC).isoformat(),
        correlacion=id_solicitud,
        causacion=str(uuid4()),
        id_peticion=id_peticion,
        id_trabajo=id_trabajo,
        id_solicitud=id_solicitud,
        id_partner=str(PARTNER_LAB),
        categoria=categoria,
        tipo_solicitud="SINIESTRO",
        tipo_red=red,
        id_politica=str(POLITICA_LAB),
        version_politica=1,
    )
    productor.send(
        mensaje,
        partition_key=id_trabajo,
        properties={"command_id": command_id, "tipo": mensaje.tipo},
    )
    print(f"OK: enviado (DOBLE DE ORQUESTACION) {categoria}/{red} id_peticion={id_peticion}")


def esperar_consulta(
    api_url: str, id_peticion: str, plazo_s: float
) -> tuple[dict[str, Any] | None, str | None]:
    limite = time.monotonic() + plazo_s
    while time.monotonic() < limite:
        estado, cuerpo = _get(f"{api_url}/cotizaciones?id_peticion={id_peticion}")
        if estado == 200:
            lista = json.loads(cuerpo)
            if lista:
                return dict(lista[0]), None
        time.sleep(1)
    return None, f"{id_peticion} no aparecio por GET /cotizaciones en {plazo_s}s"


def ejecutar(api_url: str, pulsar_url: str, topico_peticiones: str) -> str | None:
    error = comprobar_salud(api_url)
    if error:
        return error

    import pulsar

    cliente = pulsar.Client(pulsar_url, operation_timeout_seconds=5, connection_timeout_ms=5000)
    # No se cierra: ver nota de modulo. Es un proceso de un solo uso, de corta vida.

    id_f1, id_f5 = str(uuid4()), str(uuid4())
    enviar_doble(cliente, topico_peticiones, "plomeria", "GENERAL_HDA", id_f1)
    enviar_doble(cliente, topico_peticiones, "jardineria", "GENERAL_HDA", id_f5)

    propuesta, error = esperar_consulta(api_url, id_f1, PLAZO_CONSULTA_S)
    if error:
        return error
    assert propuesta is not None
    if propuesta["estado"] != "PROPUESTA" or not propuesta.get("id_proveedor"):
        return f"F1 no quedo como propuesta: {propuesta}"
    print(f"OK: F1 -> PROPUESTA proveedor={propuesta['id_proveedor']}")

    rechazo, error = esperar_consulta(api_url, id_f5, PLAZO_CONSULTA_S)
    if error:
        return error
    assert rechazo is not None
    if rechazo["estado"] != "RECHAZADA" or rechazo.get("motivo") != "SIN_OFERTA_PARA_CATEGORIA":
        return f"F5 no quedo como rechazo esperado: {rechazo}"
    print(f"OK: F5 -> RECHAZADA motivo={rechazo['motivo']}")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke de una imagen de Cotizaciones ya corriendo")
    parser.add_argument("--api-url", required=True, help="Ej: http://cotizaciones:8002")
    parser.add_argument("--pulsar-url", required=True, help="Ej: pulsar://pulsar:6650")
    parser.add_argument(
        "--topico-peticiones", default="persistent://public/default/solicitar-cotizacion-v1"
    )
    argumentos = parser.parse_args()

    error = ejecutar(
        argumentos.api_url.rstrip("/"), argumentos.pulsar_url, argumentos.topico_peticiones
    )
    if error:
        print(f"FALLO: {error}", flush=True)
        os._exit(1)
    print("SMOKE OK", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
