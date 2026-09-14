"""Muestreo de métricas de laboratorio (solo lectura), para E8/E4.

Añade una fila a un CSV cada `--intervalo` segundos durante `--duracion`, con: totales de
cotizaciones/propuestas/rechazos, nuevas en el intervalo, latencia comando->efecto (distribuida,
puede incluir desfase de reloj), pendientes del outbox y su antigüedad, y backlog/tasa/consumidores
de la suscripción propia según la API de administración de Pulsar.
"""

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, text

from cotizaciones.config.database import create_database
from cotizaciones.config.settings import Settings
from cotizaciones.modulos.cotizaciones.infraestructura.orm import CotizacionSQL
from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox

CAMPOS = [
    "instante",
    "total_cotizaciones",
    "total_propuestas",
    "total_rechazos",
    "nuevas_en_intervalo",
    "latencia_p50_s",
    "latencia_p95_s",
    "latencia_p99_s",
    "outbox_pendientes",
    "outbox_antiguedad_max_s",
    "topico_backlog",
    "topico_tasa_salida_msg_s",
    "topico_consumidores",
]


@dataclass
class Totales:
    total: int
    propuestas: int
    rechazos: int


def _percentil(valores: list[float], percentil: float) -> float | None:
    """Latencia comando->efecto: medida distribuida entre relojes de Pulsar y PostgreSQL."""
    if not valores:
        return None
    ordenados = sorted(valores)
    indice = min(len(ordenados) - 1, round(percentil / 100 * (len(ordenados) - 1)))
    return ordenados[indice]


def _admin_json(admin_url: str, ruta: str) -> dict[str, object]:
    peticion = urllib.request.Request(f"{admin_url.rstrip('/')}/admin/v2/{ruta}")
    try:
        with urllib.request.urlopen(peticion, timeout=5) as respuesta:
            return dict(json.loads(respuesta.read().decode()))
    except (urllib.error.URLError, TimeoutError):
        return {}


def muestrear_topico(admin_url: str, topico: str, suscripcion: str) -> dict[str, float | None]:
    ruta = topico.replace("://", "/") + "/stats"
    estadisticas = _admin_json(admin_url, ruta)
    suscripciones = estadisticas.get("subscriptions", {})
    candidata = suscripciones.get(suscripcion, {}) if isinstance(suscripciones, dict) else {}
    datos_suscripcion: dict[str, object] = candidata if isinstance(candidata, dict) else {}
    backlog = datos_suscripcion.get("msgBacklog")
    tasa_salida = datos_suscripcion.get("msgRateOut")
    consumidores = datos_suscripcion.get("consumers") or []
    return {
        "backlog": float(backlog) if isinstance(backlog, int | float) else None,
        "tasa_salida": float(tasa_salida) if isinstance(tasa_salida, int | float) else None,
        "consumidores": float(len(consumidores)) if isinstance(consumidores, list) else None,
    }


def muestrear_base(engine: object, desde: datetime | None) -> tuple[Totales, list[float], int]:
    from sqlalchemy import Engine

    assert isinstance(engine, Engine)
    with engine.connect() as conexion:
        total = conexion.scalar(select(func.count()).select_from(CotizacionSQL)) or 0
        propuestas = conexion.scalar(
            text("SELECT count(*) FROM cotizaciones.cotizaciones WHERE estado = 'PROPUESTA'")
        )
        rechazos = conexion.scalar(
            text("SELECT count(*) FROM cotizaciones.cotizaciones WHERE estado = 'RECHAZADA'")
        )
        if desde is None:
            nuevas = 0
            latencias: list[float] = []
        else:
            nuevas = conexion.scalar(
                text("SELECT count(*) FROM cotizaciones.cotizaciones WHERE registrada_en > :desde"),
                {"desde": desde},
            )
            filas = conexion.execute(
                text(
                    "SELECT EXTRACT(EPOCH FROM (registrada_en - instante_comando)) "
                    "FROM cotizaciones.cotizaciones WHERE registrada_en > :desde"
                ),
                {"desde": desde},
            )
            latencias = [float(fila[0]) for fila in filas]
    totales = Totales(int(total), int(propuestas or 0), int(rechazos or 0))
    return totales, latencias, int(nuevas or 0)


def main() -> None:
    configuracion = Settings.from_environment()
    parser = argparse.ArgumentParser(description="Muestreo de metricas de laboratorio (E8/E4)")
    parser.add_argument("--intervalo", type=float, default=5.0)
    parser.add_argument("--duracion", type=float, required=True)
    parser.add_argument("--admin-url", default="http://127.0.0.1:18096")
    parser.add_argument("--salida", type=Path, required=True)
    argumentos = parser.parse_args()
    if configuracion.database_url is None:
        parser.error("COTIZACIONES_DATABASE_URL es obligatoria")

    base = create_database(
        configuracion.database_url,
        pool_size=2,
        max_overflow=0,
        statement_timeout_ms=configuracion.statement_timeout_ms,
    )
    outbox = RepositorioOutbox(base.session_factory)
    nueva = not argumentos.salida.exists()
    try:
        with argumentos.salida.open("a", newline="", encoding="utf-8") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=CAMPOS)
            if nueva:
                escritor.writeheader()
            limite = time.monotonic() + argumentos.duracion
            ultimo_corte: datetime | None = None
            while True:
                ahora = datetime.now(UTC)
                totales, latencias, nuevas = muestrear_base(base.engine, ultimo_corte)
                metricas_outbox = outbox.metricas()
                topico = muestrear_topico(
                    argumentos.admin_url,
                    configuracion.topico_peticiones,
                    configuracion.suscripcion_peticiones,
                )
                fila = {
                    "instante": ahora.isoformat(),
                    "total_cotizaciones": totales.total,
                    "total_propuestas": totales.propuestas,
                    "total_rechazos": totales.rechazos,
                    "nuevas_en_intervalo": nuevas,
                    "latencia_p50_s": _percentil(latencias, 50),
                    "latencia_p95_s": _percentil(latencias, 95),
                    "latencia_p99_s": _percentil(latencias, 99),
                    "outbox_pendientes": metricas_outbox["pendientes"],
                    "outbox_antiguedad_max_s": metricas_outbox["antiguedad_segundos"],
                    "topico_backlog": topico["backlog"],
                    "topico_tasa_salida_msg_s": topico["tasa_salida"],
                    "topico_consumidores": topico["consumidores"],
                }
                escritor.writerow(fila)
                archivo.flush()
                print(json.dumps(fila, default=str), flush=True)
                ultimo_corte = ahora
                if time.monotonic() >= limite:
                    break
                time.sleep(min(argumentos.intervalo, max(0.0, limite - time.monotonic())))
    finally:
        base.close()


if __name__ == "__main__":
    main()
