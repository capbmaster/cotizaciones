"""Pulsar real para pruebas: tópicos únicos por prueba y limpieza por la API de administración."""

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pulsar
import pytest
from pulsar.schema import AvroSchema

from cotizaciones.config.settings import Settings
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)

from ..unitarias.aplicacion.datos import MENSAJE_COMANDO_F1

URL_PULSAR = os.getenv("COTIZACIONES_TEST_PULSAR_URL", "pulsar://127.0.0.1:6650")
URL_ADMIN = os.getenv("COTIZACIONES_TEST_PULSAR_ADMIN_URL", "http://127.0.0.1:18096")
ESPACIO = "persistent://public/default/"


def esperar(condicion: Callable[[], bool], segundos: float = 20.0, intervalo: float = 0.05) -> None:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return
        time.sleep(intervalo)
    raise AssertionError(f"La condicion no se cumplio en {segundos} s")


def _admin(metodo: str, ruta: str) -> Any:
    peticion = urllib.request.Request(f"{URL_ADMIN}/admin/v2/{ruta}", method=metodo)
    with urllib.request.urlopen(peticion, timeout=10) as respuesta:
        cuerpo = respuesta.read().decode()
    return json.loads(cuerpo) if cuerpo.strip() else None


def _ruta(topico: str) -> str:
    return topico.replace("://", "/")


def backlog(topico: str, suscripcion: str) -> int:
    estadisticas = _admin("GET", f"{_ruta(topico)}/stats")
    return int(estadisticas["subscriptions"].get(suscripcion, {}).get("msgBacklog", 0))


def eliminar_topico(topico: str) -> None:
    try:
        _admin("DELETE", f"{_ruta(topico)}?force=true")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise


def peticion_nueva(**cambios: Any) -> dict[str, Any]:
    """Identidades nuevas para otra petición distinta de la F1."""
    return {
        "command_id": str(uuid4()),
        "id_peticion": str(uuid4()),
        "id_trabajo": str(uuid4()),
        **cambios,
    }


@dataclass
class LaboratorioPulsar:
    cliente: Any
    configuracion: Settings
    _productor: Any = None

    def preparar_suscripcion_servicio(self) -> None:
        """Como preparar_pulsar.py: la suscripción existe antes del envío."""
        self.cliente.subscribe(
            self.configuracion.topico_peticiones,
            self.configuracion.suscripcion_peticiones,
            schema=AvroSchema(SolicitarCotizacionV1),
            consumer_type=pulsar.ConsumerType.Shared,
            initial_position=pulsar.InitialPosition.Earliest,
        ).close()

    def enviar(self, **cambios: Any) -> dict[str, Any]:
        if self._productor is None:
            self._productor = self.cliente.create_producer(
                self.configuracion.topico_peticiones,
                schema=AvroSchema(SolicitarCotizacionV1),
                send_timeout_millis=5000,
            )
        valores = {**MENSAJE_COMANDO_F1, **cambios}
        self._productor.send(
            SolicitarCotizacionV1(**valores),
            partition_key=valores["id_trabajo"],
            properties={"command_id": valores["command_id"], "tipo": valores["tipo"]},
        )
        return valores

    def suscribir(self, topico: str, nombre: str, record: Any) -> Any:
        return self.cliente.subscribe(
            topico,
            nombre,
            schema=AvroSchema(record),
            consumer_type=pulsar.ConsumerType.Shared,
            initial_position=pulsar.InitialPosition.Earliest,
        )

    def backlog_servicio(self) -> int:
        return backlog(
            self.configuracion.topico_peticiones, self.configuracion.suscripcion_peticiones
        )

    def topicos(self) -> tuple[str, str, str]:
        return (
            self.configuracion.topico_peticiones,
            self.configuracion.topico_registrada,
            self.configuracion.topico_rechazada,
        )


@contextmanager
def laboratorio_pulsar(url_base_datos: str) -> Iterator[LaboratorioPulsar]:
    try:
        _admin("GET", "clusters")
    except Exception:
        pytest.fail(
            "Pulsar requerido: docker compose up -d --wait pulsar "
            "(COTIZACIONES_TEST_PULSAR_URL / COTIZACIONES_TEST_PULSAR_ADMIN_URL)",
            pytrace=False,
        )
    sufijo = uuid4().hex[:12]
    configuracion = Settings(
        database_url=url_base_datos,
        pulsar_url=URL_PULSAR,
        topico_peticiones=f"{ESPACIO}prueba-peticiones-{sufijo}",
        topico_registrada=f"{ESPACIO}prueba-registrada-{sufijo}",
        topico_rechazada=f"{ESPACIO}prueba-rechazada-{sufijo}",
        demora_nack_ms=300,
    )
    cliente = pulsar.Client(URL_PULSAR, operation_timeout_seconds=5, connection_timeout_ms=3000)
    laboratorio = LaboratorioPulsar(cliente, configuracion)
    try:
        yield laboratorio
    finally:
        cliente.close()
        for topico in laboratorio.topicos():
            eliminar_topico(topico)
