import json
import os
import subprocess
import sys
from pathlib import Path

from cotizaciones.config.database import Database
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente
from cotizaciones.seedwork.infraestructura.despacho_outbox import DespachadorOutbox
from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox

from ..unitarias.aplicacion.datos import comando_peticion
from ..unitarias.dominio.datos import uuid_lab
from .datos import procesar_sql

RAIZ = Path(__file__).resolve().parents[2]


class _TransportePublicado:
    """Publicador falso que siempre confirma: solo se usa para marcar el outbox como enviado."""

    def publicar(self, publicacion: object) -> bool:
        return True


def despachar_todo(base: Database) -> None:
    outbox = RepositorioOutbox(base.session_factory)
    despacho = DespachadorOutbox(outbox, _TransportePublicado(), "prueba-reconciliacion")
    while despacho.despachar_lote(50) > 0:
        pass


def _entorno(base: Database) -> dict[str, str]:
    url = base.engine.url.render_as_string(hide_password=False)
    return {**os.environ, "COTIZACIONES_DATABASE_URL": url}


def test_muestrear_metricas_produce_una_fila_con_los_conteos_sembrados(
    base: Database, catalogo_v1: CatalogoVigente, tmp_path: Path
) -> None:
    procesar = procesar_sql(base)
    procesar(comando_peticion())  # F1: propuesta
    procesar(  # F5
        comando_peticion(
            id_peticion=uuid_lab("0041"),
            origen={"id_comando": uuid_lab("0042")},
            categoria="jardineria",
        )
    )

    salida = tmp_path / "metricas.csv"
    resultado = subprocess.run(
        [
            sys.executable,
            str(RAIZ / "scripts" / "muestrear_metricas.py"),
            "--intervalo",
            "1",
            "--duracion",
            "0.1",
            "--salida",
            str(salida),
        ],
        env=_entorno(base),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
    lineas = salida.read_text(encoding="utf-8").splitlines()
    assert len(lineas) >= 2  # encabezado + al menos una muestra
    fila = dict(zip(lineas[0].split(","), lineas[-1].split(","), strict=True))
    assert fila["total_cotizaciones"] == "2"
    assert fila["total_propuestas"] == "1"
    assert fila["total_rechazos"] == "1"
    assert fila["outbox_pendientes"] == "2"


def test_reconciliar_produce_los_conteos_esperados(
    base: Database, catalogo_v1: CatalogoVigente, tmp_path: Path
) -> None:
    procesar = procesar_sql(base)
    id_propuesta = uuid_lab("0021")
    id_rechazo = uuid_lab("0041")
    id_pendiente = uuid_lab("0099")
    procesar(comando_peticion(id_peticion=id_propuesta))
    procesar(
        comando_peticion(
            id_peticion=id_rechazo, origen={"id_comando": uuid_lab("0042")}, categoria="jardineria"
        )
    )
    despachar_todo(base)
    # id_pendiente nunca se procesa: debe quedar como pendiente en la reconciliacion.

    entrada = tmp_path / "enviados.jsonl"
    with entrada.open("w", encoding="utf-8") as archivo:
        for id_peticion in (id_propuesta, id_rechazo, id_pendiente):
            archivo.write(
                json.dumps(
                    {
                        "id_peticion": str(id_peticion),
                        "instante": "2026-09-14T00:00:00+00:00",
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
        env=_entorno(base),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 1, resultado.stdout  # hay un pendiente: no es consistente
    reporte = json.loads(salida.read_text(encoding="utf-8"))
    assert reporte["elegibles"] == 3
    assert reporte["propuestas"] == 1
    assert reporte["rechazos"] == 1
    assert reporte["pendientes"] == [str(id_pendiente)]
    assert reporte["cotizaciones_duplicadas_por_peticion"] == []
    assert reporte["salidas_por_cotizacion_invalidas"] == []
    assert reporte["cuadre_contable"] is True
    assert reporte["consistente"] is False

    # Al resolver el pendiente, la cohorte queda consistente.
    procesar(
        comando_peticion(
            id_peticion=id_pendiente,
            origen={"id_comando": uuid_lab("0043")},
            categoria="electricidad",
        )
    )
    despachar_todo(base)
    subprocess.run(
        [
            sys.executable,
            str(RAIZ / "scripts" / "reconciliar.py"),
            "--entrada",
            str(entrada),
            "--salida",
            str(salida),
        ],
        env=_entorno(base),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    reporte_final = json.loads(salida.read_text(encoding="utf-8"))
    assert reporte_final["pendientes"] == []
    assert reporte_final["consistente"] is True


def test_reconciliar_ignora_reentregas_de_la_misma_peticion(
    base: Database, catalogo_v1: CatalogoVigente, tmp_path: Path
) -> None:
    procesar_sql(base)(comando_peticion())
    despachar_todo(base)
    entrada = tmp_path / "enviados.jsonl"
    with entrada.open("w", encoding="utf-8") as archivo:
        for modo in ("original", "repetido"):
            archivo.write(
                json.dumps(
                    {
                        "id_peticion": str(uuid_lab("0021")),
                        "instante": "2026-09-14T00:00:00+00:00",
                        "modo": modo,
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
        env=_entorno(base),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stdout
    reporte = json.loads(salida.read_text(encoding="utf-8"))
    assert reporte["elegibles"] == 1
    assert reporte["propuestas"] == 1
