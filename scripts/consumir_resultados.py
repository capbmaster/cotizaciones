"""DOBLE LECTOR v1 de CotizacionRegistrada.v1 y CotizacionRechazada.v1.

Lee con los .avsc v1 publicados (no importa clases del productor), persiste en SQLite con
`event_id` como clave y hace ACK después del commit. Sirve también de lector histórico en E3.
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path
from time import monotonic
from typing import Any

import pulsar
from pulsar.schema import AvroSchema

from cotizaciones.config.settings import Settings

ROTULO = "DOBLE LECTOR v1"
CONTRATOS = Path(__file__).resolve().parents[1] / "docs" / "contratos"
TIPOS = {"CotizacionRegistrada.v1", "CotizacionRechazada.v1"}
SALIDA_INTERRUMPIDA = 75
CONTRADICCION = 3
SIN_MENSAJES = 4


class Contradiccion(Exception):
    pass


def persistir(mensaje: dict[str, Any], topico: str, archivo: Path) -> bool:
    """Verdadero si el hecho es nuevo; falso si es un duplicado idéntico."""
    tipo = mensaje.get("tipo")
    if tipo not in TIPOS:
        raise Contradiccion(f"Contrato no soportado: {tipo!r}")
    documento = json.dumps(mensaje, sort_keys=True, ensure_ascii=False)
    with sqlite3.connect(archivo) as conexion:
        conexion.execute(
            "CREATE TABLE IF NOT EXISTS recibidos (event_id TEXT PRIMARY KEY, "
            "id_peticion TEXT NOT NULL, tipo TEXT NOT NULL, topico TEXT NOT NULL, "
            "documento TEXT NOT NULL)"
        )
        anterior = conexion.execute(
            "SELECT documento FROM recibidos WHERE event_id = ?", (mensaje["event_id"],)
        ).fetchone()
        if anterior is not None:
            if anterior[0] != documento:
                raise Contradiccion(f"event_id {mensaje['event_id']} repetido con otro contenido")
            return False
        opuesto = conexion.execute(
            "SELECT tipo FROM recibidos WHERE id_peticion = ? AND tipo <> ?",
            (mensaje["id_peticion"], tipo),
        ).fetchone()
        if opuesto is not None:
            raise Contradiccion(
                f"La peticion {mensaje['id_peticion']} ya tiene un resultado {opuesto[0]}"
            )
        conexion.execute(
            "INSERT INTO recibidos VALUES (?, ?, ?, ?, ?)",
            (mensaje["event_id"], mensaje["id_peticion"], tipo, topico, documento),
        )
    return True


def main() -> int:
    configuracion = Settings.from_environment()
    parser = argparse.ArgumentParser(description=f"{ROTULO}: lector de resultados con SQLite")
    parser.add_argument("--url", default=configuracion.pulsar_url)
    parser.add_argument("--topico-registrada", default=configuracion.topico_registrada)
    parser.add_argument("--topico-rechazada", default=configuracion.topico_rechazada)
    parser.add_argument("--solo", choices=("registrada", "rechazada"))
    parser.add_argument("--suscripcion", required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--limite", type=int, default=1)
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument("--interrumpir-tras-commit", action="store_true")
    argumentos = parser.parse_args()
    fuentes = [
        ("registrada", argumentos.topico_registrada, "cotizacion-registrada-v1.avsc"),
        ("rechazada", argumentos.topico_rechazada, "cotizacion-rechazada-v1.avsc"),
    ]
    fuentes = [f for f in fuentes if argumentos.solo in (None, f[0])]
    timeout = configuracion.pulsar_timeout_segundos
    # Los logs del cliente C++ van al logging de Python (stderr): stdout queda como JSONL.
    cliente = pulsar.Client(
        argumentos.url,
        operation_timeout_seconds=timeout,
        connection_timeout_ms=timeout * 1000,
        logger=logging.getLogger("pulsar"),
    )
    try:
        consumidores = []
        for _, topico, avsc in fuentes:
            esquema = json.loads((CONTRATOS / avsc).read_text(encoding="utf-8"))
            consumidor = cliente.subscribe(
                topico,
                argumentos.suscripcion,
                schema=AvroSchema(None, schema_definition=esquema),
                consumer_type=pulsar.ConsumerType.Shared,
                initial_position=pulsar.InitialPosition.Earliest,
            )
            consumidores.append((consumidor, topico))
        procesados = 0
        limite_tiempo = monotonic() + argumentos.timeout_ms / 1000
        while procesados < argumentos.limite and monotonic() < limite_tiempo:
            for consumidor, topico in consumidores:
                try:
                    mensaje = consumidor.receive(timeout_millis=200)
                except pulsar.Timeout:
                    continue
                valor = dict(mensaje.value())
                try:
                    nuevo = persistir(valor, topico, argumentos.base)
                except Contradiccion as error:
                    print(f"{ROTULO}: CONTRADICCION {error}", file=sys.stderr, flush=True)
                    return CONTRADICCION
                if argumentos.interrumpir_tras_commit:
                    print(f"{ROTULO}: interrumpido tras commit y antes del ACK", flush=True)
                    return SALIDA_INTERRUMPIDA
                consumidor.acknowledge(mensaje)
                procesados += 1
                print(
                    json.dumps(
                        {
                            "doble": ROTULO,
                            "event_id": valor["event_id"],
                            "tipo": valor["tipo"],
                            "version_contrato": valor["version_contrato"],
                            "topico": topico,
                            "persistido": nuevo,
                        }
                    ),
                    flush=True,
                )
                if procesados >= argumentos.limite:
                    break
        if procesados < argumentos.limite:
            print(
                f"{ROTULO}: solo {procesados} de {argumentos.limite} dentro del plazo",
                file=sys.stderr,
            )
            return SIN_MENSAJES
        return 0
    finally:
        cliente.close()


if __name__ == "__main__":
    sys.exit(main())
