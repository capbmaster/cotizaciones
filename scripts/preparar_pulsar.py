import argparse
import json
import time
import urllib.error
import urllib.request
from typing import Any

import pulsar
from pulsar.schema import AvroSchema

from cotizaciones.config.settings import Settings
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.eventos import (
    CotizacionRechazadaV1,
    CotizacionRegistradaV1,
)

SUSCRIPCIONES_REGISTRADA = (
    "orquestacion-cotizacion-registrada-v1",
    "seguimiento-cotizacion-registrada",
)
SUSCRIPCIONES_RECHAZADA = (
    "orquestacion-cotizacion-rechazada-v1",
    "seguimiento-cotizacion-rechazada-v1",
)
HISTORICOS_E3 = tuple(f"e3-historico-{numero:02d}" for numero in range(1, 6))
MIB = 1024 * 1024


def _admin(metodo: str, url: str, cuerpo: Any = None) -> str:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(
        url, data=datos, method=metodo, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(peticion, timeout=10) as respuesta:
            return str(respuesta.read().decode())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{metodo} {url}: HTTP {error.code} {error.read().decode()}") from error


def aplicar_politicas(
    admin_url: str,
    topico: str,
    backlog_mib: int,
    backlog_minutos: int,
    retencion_minutos: int,
    retencion_mib: int,
) -> dict[str, Any]:
    """Cuotas de backlog primero y retención después: Pulsar 4.1 exige retención > cuota."""
    base = f"{admin_url.rstrip('/')}/admin/v2/{topico.replace('://', '/')}"
    _admin(
        "POST",
        f"{base}/backlogQuota?backlogQuotaType=destination_storage",
        {"limitSize": backlog_mib * MIB, "policy": "producer_exception"},
    )
    _admin(
        "POST",
        f"{base}/backlogQuota?backlogQuotaType=message_age",
        {"limitTime": backlog_minutos * 60, "policy": "producer_exception"},
    )
    _admin(
        "POST",
        f"{base}/retention",
        {"retentionTimeInMinutes": retencion_minutos, "retentionSizeInMB": retencion_mib},
    )
    # Las políticas de tópico se aplican de forma asíncrona: leer de vuelta hasta verlas.
    for _ in range(40):
        retencion = _admin("GET", f"{base}/retention").strip()
        cuotas = _admin("GET", f"{base}/backlogQuotaMap").strip()
        if retencion not in ("", "null") and cuotas not in ("", "{}", "null"):
            return {
                "topico": topico,
                "retencion": json.loads(retencion),
                "cuotas": json.loads(cuotas),
            }
        time.sleep(0.25)
    raise RuntimeError(f"Las politicas de {topico} no se pudieron leer de vuelta")


def aplicar_compatibilidad(admin_url: str, topico: str, estrategia: str) -> str:
    """Fija la estrategia de compatibilidad de esquema del topico y la lee de vuelta (Paso 57)."""
    base = f"{admin_url.rstrip('/')}/admin/v2/{topico.replace('://', '/')}"
    ruta = f"{base}/schemaCompatibilityStrategy"
    _admin("PUT", ruta, estrategia)
    for _ in range(40):
        leida = _admin("GET", ruta).strip().strip('"')
        if leida == estrategia:
            return leida
        time.sleep(0.25)
    raise RuntimeError(f"La compatibilidad de {topico} no quedo en {estrategia!r}")


def _suscribir(cliente: Any, topico: str, nombre: str, esquema: Any) -> None:
    # Crear una suscripción existente no reinicia su cursor.
    cliente.subscribe(
        topico,
        nombre,
        schema=esquema,
        consumer_type=pulsar.ConsumerType.Shared,
        initial_position=pulsar.InitialPosition.Earliest,
    ).close()
    print(f"Suscripcion disponible: {nombre} en {topico}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Registra esquemas y crea las suscripciones durables de 00 §1 antes del envio."
    )
    parser.add_argument("--admin-url", help="Aplica cuota de backlog y retencion por topico")
    parser.add_argument(
        "--compatibilidad",
        help=(
            "Estrategia de compatibilidad de esquema del topico de propuestas "
            "(requiere --admin-url)"
        ),
    )
    parser.add_argument("--historicos-e3", action="store_true", help="Crea e3-historico-01..05")
    parser.add_argument("--backlog-mib", type=int, default=50)
    parser.add_argument("--backlog-minutos", type=int, default=30)
    parser.add_argument("--retencion-minutos", type=int, default=60)
    parser.add_argument("--retencion-mib", type=int, default=100)
    argumentos = parser.parse_args()
    if argumentos.retencion_mib <= argumentos.backlog_mib:
        parser.error("--retencion-mib debe superar --backlog-mib (regla del broker)")
    if argumentos.compatibilidad and not argumentos.admin_url:
        parser.error("--compatibilidad requiere --admin-url")
    configuracion = Settings.from_environment()
    timeout = configuracion.pulsar_timeout_segundos
    cliente = pulsar.Client(
        configuracion.pulsar_url,
        operation_timeout_seconds=timeout,
        connection_timeout_ms=timeout * 1000,
    )
    try:
        registrada = AvroSchema(CotizacionRegistradaV1)
        rechazada = AvroSchema(CotizacionRechazadaV1)
        for topico, esquema, nombre in (
            (configuracion.topico_registrada, registrada, "CotizacionRegistradaV1"),
            (configuracion.topico_rechazada, rechazada, "CotizacionRechazadaV1"),
        ):
            cliente.create_producer(topico, schema=esquema).close()
            print(f"Esquema registrado: {nombre} en {topico}")
        _suscribir(
            cliente,
            configuracion.topico_peticiones,
            configuracion.suscripcion_peticiones,
            AvroSchema(SolicitarCotizacionV1),
        )
        historicos = HISTORICOS_E3 if argumentos.historicos_e3 else ()
        for nombre in SUSCRIPCIONES_REGISTRADA + historicos:
            _suscribir(cliente, configuracion.topico_registrada, nombre, registrada)
        for nombre in SUSCRIPCIONES_RECHAZADA:
            _suscribir(cliente, configuracion.topico_rechazada, nombre, rechazada)
    finally:
        cliente.close()
    if argumentos.admin_url:
        for topico in (
            configuracion.topico_peticiones,
            configuracion.topico_registrada,
            configuracion.topico_rechazada,
        ):
            politicas = aplicar_politicas(
                argumentos.admin_url,
                topico,
                argumentos.backlog_mib,
                argumentos.backlog_minutos,
                argumentos.retencion_minutos,
                argumentos.retencion_mib,
            )
            print(json.dumps(politicas, ensure_ascii=False))
        if argumentos.compatibilidad:
            leida = aplicar_compatibilidad(
                argumentos.admin_url, configuracion.topico_registrada, argumentos.compatibilidad
            )
            print(f"Compatibilidad de {configuracion.topico_registrada}: {leida}")


if __name__ == "__main__":
    main()
