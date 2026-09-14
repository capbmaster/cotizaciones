"""Reconciliación de una cohorte: compara el JSONL de peticiones esperadas contra la base.

Entrada: el JSONL que produce `scripts/enviar_peticion.py --salida` (u otro con al menos
`id_peticion`; usa `instante` para acotar la ventana y `modo` para descartar variantes que no
crean una petición nueva). Cada `id_peticion` distinto es una petición elegible: debe terminar en
exactamente una cotización (PROPUESTA o RECHAZADA) con exactamente una salida confirmada.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from cotizaciones.config.database import create_database
from cotizaciones.config.settings import Settings

# Modos de enviar_peticion.py que reenvían la MISMA identidad de petición (no crean otra elegible).
MODOS_MISMA_PETICION = {"repetido", "nuevo-comando", "contradictoria"}


def leer_elegibles(archivo: Path, desde: datetime | None, hasta: datetime | None) -> list[str]:
    elegibles: dict[str, None] = {}
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        registro = json.loads(linea)
        if desde is not None or hasta is not None:
            instante = datetime.fromisoformat(registro["instante"])
            if desde is not None and instante < desde:
                continue
            if hasta is not None and instante > hasta:
                continue
        if registro.get("modo") in MODOS_MISMA_PETICION:
            continue  # misma id_peticion que su "original"; no es una elegible adicional
        elegibles[registro["id_peticion"]] = None
    return list(elegibles)


def reconciliar(engine: Any, elegibles: list[str]) -> dict[str, Any]:
    if not elegibles:
        return {
            "elegibles": 0,
            "propuestas": 0,
            "rechazos": 0,
            "pendientes": [],
            "cotizaciones_duplicadas_por_peticion": [],
            "salidas_por_cotizacion_invalidas": [],
        }
    with engine.connect() as conexion:
        filas = conexion.execute(
            text(
                "SELECT id, id_peticion, estado FROM cotizaciones.cotizaciones "
                "WHERE id_peticion = ANY(:ids)"
            ),
            {"ids": elegibles},
        ).all()
        duplicadas = (
            conexion.execute(
                text(
                    "SELECT id_peticion FROM cotizaciones.cotizaciones "
                    "WHERE id_peticion = ANY(:ids) "
                    "GROUP BY id_peticion HAVING count(*) > 1"
                ),
                {"ids": elegibles},
            )
            .scalars()
            .all()
        )
        ids_cotizacion = [str(fila.id) for fila in filas]
        salidas_invalidas: list[str] = []
        if ids_cotizacion:
            conteos = conexion.execute(
                text(
                    "SELECT documento->>'id_cotizacion' AS id_cotizacion, "
                    "count(*) FILTER (WHERE enviada_en IS NOT NULL) AS enviadas, "
                    "count(*) AS totales "
                    "FROM mensajeria.outbox "
                    "WHERE documento->>'id_cotizacion' = ANY(:ids) "
                    "GROUP BY documento->>'id_cotizacion'"
                ),
                {"ids": ids_cotizacion},
            ).all()
            por_cotizacion = {fila.id_cotizacion: fila for fila in conteos}
            for id_cotizacion in ids_cotizacion:
                fila = por_cotizacion.get(id_cotizacion)
                if fila is None or fila.enviadas != 1 or fila.totales != 1:
                    salidas_invalidas.append(id_cotizacion)

    resueltas = {str(fila.id_peticion) for fila in filas}
    pendientes = sorted(set(elegibles) - resueltas)
    propuestas = sum(1 for fila in filas if fila.estado == "PROPUESTA")
    rechazos = sum(1 for fila in filas if fila.estado == "RECHAZADA")
    return {
        "elegibles": len(elegibles),
        "propuestas": propuestas,
        "rechazos": rechazos,
        "pendientes": pendientes,
        "cotizaciones_duplicadas_por_peticion": sorted(duplicadas),
        "salidas_por_cotizacion_invalidas": sorted(salidas_invalidas),
    }


def main() -> int:
    configuracion = Settings.from_environment()
    parser = argparse.ArgumentParser(
        description="Reconcilia una cohorte del JSONL de enviar_peticion.py contra la base"
    )
    parser.add_argument("--entrada", type=Path, required=True)
    parser.add_argument("--desde", type=datetime.fromisoformat)
    parser.add_argument("--hasta", type=datetime.fromisoformat)
    parser.add_argument("--salida", type=Path, required=True)
    argumentos = parser.parse_args()
    if configuracion.database_url is None:
        parser.error("COTIZACIONES_DATABASE_URL es obligatoria")

    elegibles = leer_elegibles(argumentos.entrada, argumentos.desde, argumentos.hasta)
    base = create_database(
        configuracion.database_url,
        pool_size=1,
        max_overflow=0,
        statement_timeout_ms=configuracion.statement_timeout_ms,
    )
    try:
        resultado = reconciliar(base.engine, elegibles)
    finally:
        base.close()

    # Identidad contable de 00 §47: elegibles = propuestas + rechazos + pendientes. Es una
    # verificación de conteo, no un criterio de éxito: una cohorte con pendientes cuadra igual.
    total_resuelto = resultado["propuestas"] + resultado["rechazos"] + len(resultado["pendientes"])
    resultado["cuadre_contable"] = resultado["elegibles"] == total_resuelto
    # Criterio de éxito (Paso 48/E8): cero pendientes, cero duplicados, una salida enviada c/u.
    resultado["consistente"] = (
        resultado["cuadre_contable"]
        and not resultado["pendientes"]
        and not resultado["cotizaciones_duplicadas_por_peticion"]
        and not resultado["salidas_por_cotizacion_invalidas"]
    )
    argumentos.salida.write_text(
        json.dumps(resultado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return 0 if resultado["consistente"] else 1


if __name__ == "__main__":
    sys.exit(main())
