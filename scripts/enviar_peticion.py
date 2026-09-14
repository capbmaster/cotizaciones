"""DOBLE DE ORQUESTACION: envía SolicitarCotizacion.v1 para desarrollo y pruebas.

No es el servicio de Orquestación ni lo sustituye en la integración real (ver docs/contratos).
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pulsar
from pulsar.schema import AvroSchema

from cotizaciones.config.settings import Settings
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)

ROTULO = "DOBLE DE ORQUESTACION"
TIPO = "SolicitarCotizacion.v1"
PARTNER_LAB = UUID("00000000-0000-0000-0000-000000000002")
POLITICA_LAB = UUID("00000000-0000-0000-0000-000000000003")


def construir_mensaje(command_id: UUID, instante: str, datos: dict[str, Any]) -> Any:
    return SolicitarCotizacionV1(
        command_id=str(command_id),
        tipo=TIPO,
        version_contrato=1,
        instante=instante,
        correlacion=datos["id_solicitud"],
        **datos,
    )


def main() -> int:
    configuracion = Settings.from_environment()
    parser = argparse.ArgumentParser(
        description=f"{ROTULO}: envia SolicitarCotizacion.v1. No es el servicio de Orquestacion."
    )
    parser.add_argument("--url", default=configuracion.pulsar_url)
    parser.add_argument("--topico", default=configuracion.topico_peticiones)
    parser.add_argument("--categoria", default="plomeria")
    parser.add_argument(
        "--red", choices=("GENERAL_HDA", "HOMOLOGADA_PARTNER"), default="GENERAL_HDA"
    )
    parser.add_argument(
        "--tipo-solicitud", choices=("SINIESTRO", "INSTALACION"), default="SINIESTRO"
    )
    parser.add_argument("--id-partner", type=UUID, default=PARTNER_LAB)
    parser.add_argument("--id-peticion", type=UUID, help="Solo con --cantidad 1")
    parser.add_argument("--cantidad", type=int, default=1)
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--repetir-comando", action="store_true", help="Mismo mensaje dos veces")
    modo.add_argument(
        "--nuevo-comando-misma-peticion",
        action="store_true",
        help="Misma peticion con otro command_id",
    )
    modo.add_argument(
        "--contradictoria",
        action="store_true",
        help="Misma peticion, otro command_id y otra categoria (conflicto)",
    )
    parser.add_argument("--salida", type=Path, help="JSONL con los IDs enviados")
    argumentos = parser.parse_args()
    if argumentos.cantidad <= 0:
        parser.error("--cantidad debe ser positiva")
    if argumentos.id_peticion is not None and argumentos.cantidad != 1:
        parser.error("--id-peticion solo admite --cantidad 1")

    timeout = configuracion.pulsar_timeout_segundos
    # Los logs del cliente C++ van al logging de Python (stderr), no a la salida del doble.
    cliente = pulsar.Client(
        argumentos.url,
        operation_timeout_seconds=timeout,
        connection_timeout_ms=timeout * 1000,
        logger=logging.getLogger("pulsar"),
    )
    registros: list[dict[str, Any]] = []
    try:
        productor = cliente.create_producer(
            argumentos.topico,
            schema=AvroSchema(SolicitarCotizacionV1),
            send_timeout_millis=timeout * 1000,
        )
        for _ in range(argumentos.cantidad):
            id_solicitud = uuid4()
            datos: dict[str, Any] = {
                "causacion": str(uuid4()),
                "id_peticion": str(argumentos.id_peticion or uuid4()),
                "id_trabajo": str(uuid4()),
                "id_solicitud": str(id_solicitud),
                "id_partner": str(argumentos.id_partner),
                "categoria": argumentos.categoria,
                "tipo_solicitud": argumentos.tipo_solicitud,
                "tipo_red": argumentos.red,
                "id_politica": str(POLITICA_LAB),
                "version_politica": 1,
            }
            original = (uuid4(), datetime.now(UTC).isoformat(), datos, "original")
            envios = [original]
            if argumentos.repetir_comando:
                envios.append((original[0], original[1], datos, "repetido"))
            elif argumentos.nuevo_comando_misma_peticion:
                envios.append((uuid4(), datetime.now(UTC).isoformat(), datos, "nuevo-comando"))
            elif argumentos.contradictoria:
                otra = "electricidad" if argumentos.categoria != "electricidad" else "plomeria"
                envios.append(
                    (
                        uuid4(),
                        datetime.now(UTC).isoformat(),
                        {**datos, "categoria": otra},
                        "contradictoria",
                    )
                )
            for command_id, instante, contenido, nombre_modo in envios:
                productor.send(
                    construir_mensaje(command_id, instante, contenido),
                    partition_key=contenido["id_trabajo"],
                    properties={"command_id": str(command_id), "tipo": TIPO},
                )
                registro = {
                    "doble": ROTULO,
                    "modo": nombre_modo,
                    "command_id": str(command_id),
                    "instante": instante,
                    **contenido,
                }
                registros.append(registro)
                print(
                    f"{ROTULO}: enviado {nombre_modo} command_id={command_id} "
                    f"id_peticion={contenido['id_peticion']} categoria={contenido['categoria']}",
                    flush=True,
                )
    finally:
        cliente.close()
    if argumentos.salida is not None:
        with argumentos.salida.open("a", encoding="utf-8") as archivo:
            for registro in registros:
                archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
