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


ARCHIVO_V2 = RAIZ / "datos" / "catalogos" / "catalogo-v2.json"


def _documento_registrada(base: Database, id_cotizacion: object) -> dict[str, Any]:
    """El documento archivado en mensajeria.eventos para el hecho registrado de esa cotizacion."""
    with base.engine.connect() as conexion:
        documento = conexion.scalar(
            text(
                "SELECT documento FROM mensajeria.eventos WHERE documento->>'id_cotizacion' = :id"
            ).bindparams(id=str(id_cotizacion))
        )
    assert documento is not None
    return dict(documento)


def test_f8_catalogo_v2_real_publica_duraciones_30_90_null(
    base: Database, catalogo_v1: CatalogoVigente
) -> None:
    """00 §9 F8: tras activar v2, plomeria/cerrajeria/electricidad dan 30/90/null; una peticion
    resuelta antes del cambio conserva su resultado y su hecho original al reenviarse."""
    from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
        mensaje_registrada,
    )

    procesar = procesar_sql(base)
    previa = procesar(comando_peticion())  # F1, resuelta con el catalogo v1 (sin duracion)

    resultado = cargar(base, "--archivo", str(ARCHIVO_V2), "--activar")
    assert resultado.returncode == 0, resultado.stderr
    assert "Version activa: 2" in resultado.stdout
    assert versiones_activas(base) == [2]

    casos = [
        ("plomeria", uuid_lab("00a0"), 30),
        ("cerrajeria", uuid_lab("00a1"), 90),
        ("electricidad", uuid_lab("00a2"), None),
    ]
    for indice, (categoria, id_peticion, duracion_esperada) in enumerate(casos):
        nueva = procesar(
            comando_peticion(
                id_peticion=id_peticion,
                origen={"id_comando": uuid_lab(f"01{indice:02d}")},
                categoria=categoria,
            )
        )
        assert nueva.nueva is True
        with crear_uow_cotizaciones(base) as unidad:
            fila = unidad.cotizaciones.obtener_por_peticion(id_peticion)
        assert fila is not None and fila.resultado.oferta is not None
        assert fila.resultado.oferta.duracion_estimada_minutos == duracion_esperada
        mensaje = mensaje_registrada(_documento_registrada(base, nueva.id_cotizacion))
        assert mensaje.version_contrato == 2
        assert mensaje.duracion_estimada_minutos == duracion_esperada

    # La reentrega de la peticion previa (resuelta con v1, antes del cambio) conserva su
    # resultado original: la duracion sigue nula y no se genera un segundo hecho.
    documento_antes = _documento_registrada(base, previa.id_cotizacion)
    reentrega = procesar(comando_peticion())
    assert reentrega.nueva is False
    assert reentrega.id_cotizacion == previa.id_cotizacion
    assert _documento_registrada(base, previa.id_cotizacion) == documento_antes
    with crear_uow_cotizaciones(base) as unidad:
        fila_previa = unidad.cotizaciones.obtener_por_peticion(ID_PETICION)
    assert fila_previa is not None and fila_previa.resultado.oferta is not None
    assert fila_previa.resultado.oferta.duracion_estimada_minutos is None

    # Reenviar ese hecho historico usa hoy el escritor v2 (version_contrato=2), pero la
    # duracion viene del documento archivado (formato 1, sin la clave): nunca se relee el
    # catalogo activo, y nunca se republica un hecho distinto del que ya ocurrio.
    mensaje_previo = mensaje_registrada(documento_antes)
    assert mensaje_previo.version_contrato == 2
    assert mensaje_previo.duracion_estimada_minutos is None
