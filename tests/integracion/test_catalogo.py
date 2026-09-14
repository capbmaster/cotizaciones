import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text

from cotizaciones.config.database import Database
from cotizaciones.config.persistencia import crear_uow_cotizaciones
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoInvalido
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente
from cotizaciones.modulos.cotizaciones.infraestructura.orm import CotizacionSQL
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import huella_catalogo

from ..unitarias.aplicacion.datos import comando_peticion
from ..unitarias.dominio.datos import A101, A102, ID_PETICION, catalogo_laboratorio, uuid_lab
from .datos import procesar_sql

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "scripts" / "cargar_catalogo.py"
ARCHIVO_V1 = RAIZ / "datos" / "catalogos" / "catalogo-v1.json"


def cargar(base: Database, *argumentos: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argumentos],
        env={
            **os.environ,
            "COTIZACIONES_DATABASE_URL": base.engine.url.render_as_string(hide_password=False),
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def escribir(directorio: Path, documento: dict[str, Any]) -> Path:
    archivo = directorio / f"catalogo-v{documento['version']}.json"
    archivo.write_text(json.dumps(documento), encoding="utf-8")
    return archivo


def versiones_activas(base: Database) -> list[int]:
    with base.engine.connect() as conexion:
        return list(
            conexion.scalars(text("SELECT version FROM cotizaciones.catalogos WHERE activo"))
        )


def cantidad(base: Database, tabla: str) -> int:
    with base.engine.connect() as conexion:
        return int(conexion.scalar(text(f"SELECT count(*) FROM cotizaciones.{tabla}")) or 0)


def test_el_script_registra_y_activa_de_forma_idempotente(base: Database) -> None:
    primera = cargar(base, "--activar")
    assert primera.returncode == 0, primera.stderr
    assert "nueva" in primera.stdout
    assert "Version activa: 1" in primera.stdout
    segunda = cargar(base, "--activar")
    assert segunda.returncode == 0, segunda.stderr
    assert "ya existia" in segunda.stdout
    assert "Version activa: 1" in segunda.stdout
    assert cantidad(base, "catalogos") == 1
    assert cantidad(base, "ofertas_catalogo") == 5
    assert versiones_activas(base) == [1]


def test_sin_activar_la_version_queda_registrada_e_inactiva(base: Database) -> None:
    resultado = cargar(base)
    assert resultado.returncode == 0, resultado.stderr
    assert "Version activa: ninguna" in resultado.stdout
    assert versiones_activas(base) == []


def test_misma_version_con_otro_contenido_termina_con_codigo_2(
    base: Database, tmp_path: Path
) -> None:
    assert cargar(base).returncode == 0
    alterado = json.loads(ARCHIVO_V1.read_text(encoding="utf-8"))
    alterado["ofertas"][0]["importe_menor"] = 99_000_000
    resultado = cargar(base, "--archivo", str(escribir(tmp_path, alterado)), "--activar")
    assert resultado.returncode == 2
    assert "otro contenido" in resultado.stderr
    with base.engine.connect() as conexion:
        importes = set(
            conexion.scalars(text("SELECT importe_menor FROM cotizaciones.ofertas_catalogo"))
        )
    assert 99_000_000 not in importes
    assert versiones_activas(base) == []


def test_registrar_la_misma_version_y_huella_no_hace_nada(base: Database) -> None:
    catalogo = catalogo_laboratorio()
    with crear_uow_cotizaciones(base) as unidad:
        assert unidad.catalogos.registrar_version(catalogo, huella_catalogo(catalogo)) is True
        unidad.confirmar()
    with crear_uow_cotizaciones(base) as unidad:
        assert unidad.catalogos.registrar_version(catalogo, huella_catalogo(catalogo)) is False
        with pytest.raises(CatalogoInvalido):
            unidad.catalogos.registrar_version(catalogo, "otra-huella")


def test_activar_una_version_inexistente_falla(base: Database) -> None:
    with pytest.raises(ValueError, match="no existe"), crear_uow_cotizaciones(base) as unidad:
        unidad.catalogos.activar(9)


def test_activar_otra_version_deja_una_sola_activa_y_conserva_cotizaciones_previas(
    base: Database, catalogo_v1: CatalogoVigente, tmp_path: Path
) -> None:
    procesar = procesar_sql(base)
    original = procesar(comando_peticion())
    v2 = {
        "version": 2,
        "ofertas": [
            {
                "id_proveedor": str(A102),
                "categoria": "plomeria",
                "tipo_red": "GENERAL_HDA",
                "id_partner": None,
                "importe_menor": 11_000_000,
                "moneda": "COP",
            }
        ],
    }
    resultado = cargar(base, "--archivo", str(escribir(tmp_path, v2)), "--activar")
    assert resultado.returncode == 0, resultado.stderr
    assert "Version activa: 2" in resultado.stdout
    assert versiones_activas(base) == [2]

    reentrega = procesar(comando_peticion(origen={"id_comando": uuid_lab("0023")}))
    nueva = procesar(
        comando_peticion(id_peticion=uuid_lab("0040"), origen={"id_comando": uuid_lab("0041")})
    )
    assert reentrega.id_cotizacion == original.id_cotizacion
    with base.session_factory() as sesion:
        filas = {f.id_peticion: f for f in sesion.scalars(select(CotizacionSQL))}
    assert (filas[ID_PETICION].version_catalogo, filas[ID_PETICION].id_proveedor) == (1, A101)
    assert (filas[uuid_lab("0040")].version_catalogo, filas[uuid_lab("0040")].id_proveedor) == (
        2,
        A102,
    )
    assert nueva.nueva is True
