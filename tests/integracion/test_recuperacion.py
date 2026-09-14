"""Paso 48: caída y recuperación con la misma base, suscripción y configuración."""

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from cotizaciones.api.app import create_app
from cotizaciones.config.database import Database
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente

from .datos import contar, marcas_sin_efecto, salidas_enviadas
from .pulsar import LaboratorioPulsar, esperar, peticion_nueva

RAIZ = Path(__file__).resolve().parents[2]


def _entregadas(base: Database) -> int:
    from cotizaciones.modulos.cotizaciones.infraestructura.orm import CotizacionSQL

    return contar(base, CotizacionSQL)


def test_caida_y_recuperacion_con_dos_cohortes(
    base: Database,
    catalogo_v1: CatalogoVigente,
    laboratorio: LaboratorioPulsar,
    tmp_path: Path,
) -> None:
    laboratorio.preparar_suscripcion_servicio()
    cohorte_a = [laboratorio.enviar(**peticion_nueva()) for _ in range(5)]

    # 1) Servicio arriba: la cohorte A se resuelve.
    with TestClient(create_app(laboratorio.configuracion)):
        esperar(lambda: _entregadas(base) == len(cohorte_a), segundos=30)
        esperar(lambda: salidas_enviadas(base) == len(cohorte_a), segundos=30)
    assert laboratorio.backlog_servicio() == 0

    # 2) Servicio caído (el "with" ya cerró API, consumo y despacho juntos): la cohorte B
    #    se acumula en Pulsar sin que aparezca ninguna fila nueva.
    cohorte_b = [laboratorio.enviar(**peticion_nueva()) for _ in range(5)]
    esperar(lambda: laboratorio.backlog_servicio() == len(cohorte_b), segundos=15)
    assert _entregadas(base) == len(cohorte_a)

    # 3) Reabrir con la MISMA base, suscripción y configuración: B se resuelve sin tocar A.
    with TestClient(create_app(laboratorio.configuracion)):
        esperar(
            lambda: _entregadas(base) == len(cohorte_a) + len(cohorte_b),
            segundos=30,
        )
        esperar(
            lambda: salidas_enviadas(base) == len(cohorte_a) + len(cohorte_b),
            segundos=30,
        )
    assert laboratorio.backlog_servicio() == 0

    # 4) Reconciliar A ∪ B con el script real: cero pendientes, cero duplicados, una salida
    #    enviada por cotización, inbox intacto (ninguna marca sin cotización asociada).
    entrada = tmp_path / "cohorte.jsonl"
    with entrada.open("w", encoding="utf-8") as archivo:
        for enviado in cohorte_a + cohorte_b:
            archivo.write(
                json.dumps(
                    {
                        "id_peticion": enviado["id_peticion"],
                        "instante": enviado["instante"],
                        "modo": "original",
                    }
                )
                + "\n"
            )
    salida = tmp_path / "reconciliacion.json"
    resultado = subprocess.run(
        [
            sys.executable,
            str(RAIZ / "scripts" / "reconciliar.py"),
            "--entrada",
            str(entrada),
            "--salida",
            str(salida),
        ],
        env={
            **os.environ,
            "COTIZACIONES_DATABASE_URL": base.engine.url.render_as_string(hide_password=False),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    reporte = json.loads(salida.read_text(encoding="utf-8"))
    assert reporte["elegibles"] == len(cohorte_a) + len(cohorte_b)
    assert reporte["pendientes"] == []
    assert reporte["cotizaciones_duplicadas_por_peticion"] == []
    assert reporte["salidas_por_cotizacion_invalidas"] == []
    assert marcas_sin_efecto(base) == 0
