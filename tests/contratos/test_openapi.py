import json
from pathlib import Path

from cotizaciones.api.app import create_app
from cotizaciones.config.settings import Settings

ARCHIVO = Path(__file__).resolve().parents[2] / "docs" / "contratos" / "openapi.json"


def test_openapi_exportado_coincide_con_la_app_actual() -> None:
    publicado = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    actual = create_app(Settings()).openapi()
    assert publicado == actual


def test_rutas_de_cotizaciones_estan_documentadas() -> None:
    publicado = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    assert "/cotizaciones/{id_cotizacion}" in publicado["paths"]
    assert "/cotizaciones" in publicado["paths"]
