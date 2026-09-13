import os
from dataclasses import replace
from typing import Any

import pytest

from cotizaciones.config.settings import Settings


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in list(os.environ):
        if nombre.startswith("COTIZACIONES_"):
            monkeypatch.delenv(nombre)


def test_valores_predeterminados() -> None:
    configuracion = Settings()
    assert configuracion.service_name == "cotizaciones"
    assert configuracion.database_url is None
    assert configuracion.pool_size == 5
    assert configuracion.max_overflow == 5
    assert configuracion.statement_timeout_ms == 3000
    assert configuracion.pulsar_url == "pulsar://127.0.0.1:6650"
    assert configuracion.topico_peticiones == "persistent://public/default/solicitar-cotizacion-v1"
    assert configuracion.suscripcion_peticiones == "cotizaciones-peticiones-v1"
    assert configuracion.topico_registrada == "persistent://public/default/cotizacion-registrada-v1"
    assert configuracion.topico_rechazada == "persistent://public/default/cotizacion-rechazada-v1"
    assert configuracion.pulsar_timeout_segundos == 3
    assert configuracion.receptor_cola == 1
    assert configuracion.demora_nack_ms == 5000
    assert configuracion.retardo_laboratorio_ms == 0


def test_entorno_vacio_equivale_a_predeterminados() -> None:
    assert Settings.from_environment() == Settings()


def test_lee_variables_de_entorno_en_cada_llamada(monkeypatch: pytest.MonkeyPatch) -> None:
    valores = {
        "COTIZACIONES_SERVICE_NAME": "cotizaciones-prueba",
        "COTIZACIONES_DATABASE_URL": "postgresql+psycopg://u:p@db:5432/c",
        "COTIZACIONES_DB_POOL_SIZE": "7",
        "COTIZACIONES_DB_MAX_OVERFLOW": "0",
        "COTIZACIONES_DB_STATEMENT_TIMEOUT_MS": "1500",
        "COTIZACIONES_PULSAR_URL": "pulsar://pulsar:6650",
        "COTIZACIONES_TOPICO_PETICIONES": "persistent://public/default/peticiones-prueba",
        "COTIZACIONES_SUSCRIPCION_PETICIONES": "suscripcion-prueba",
        "COTIZACIONES_TOPICO_REGISTRADA": "persistent://public/default/registrada-prueba",
        "COTIZACIONES_TOPICO_RECHAZADA": "persistent://public/default/rechazada-prueba",
        "COTIZACIONES_PULSAR_TIMEOUT_SEGUNDOS": "2",
        "COTIZACIONES_PULSAR_RECEPTOR_COLA": "4",
        "COTIZACIONES_PULSAR_DEMORA_NACK_MS": "250",
        "COTIZACIONES_RETARDO_LABORATORIO_MS": "15",
    }
    for nombre, valor in valores.items():
        monkeypatch.setenv(nombre, valor)

    assert Settings.from_environment() == Settings(
        service_name="cotizaciones-prueba",
        database_url="postgresql+psycopg://u:p@db:5432/c",
        pool_size=7,
        max_overflow=0,
        statement_timeout_ms=1500,
        pulsar_url="pulsar://pulsar:6650",
        topico_peticiones="persistent://public/default/peticiones-prueba",
        suscripcion_peticiones="suscripcion-prueba",
        topico_registrada="persistent://public/default/registrada-prueba",
        topico_rechazada="persistent://public/default/rechazada-prueba",
        pulsar_timeout_segundos=2,
        receptor_cola=4,
        demora_nack_ms=250,
        retardo_laboratorio_ms=15,
    )

    monkeypatch.setenv("COTIZACIONES_SERVICE_NAME", "otro-nombre")
    assert Settings.from_environment().service_name == "otro-nombre"


@pytest.mark.parametrize("valor", ["", "   "])
def test_url_de_base_en_blanco_equivale_a_ausente(
    monkeypatch: pytest.MonkeyPatch, valor: str
) -> None:
    monkeypatch.setenv("COTIZACIONES_DATABASE_URL", valor)
    assert Settings.from_environment().database_url is None


def test_entero_invalido_en_entorno_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COTIZACIONES_DB_POOL_SIZE", "cinco")
    with pytest.raises(ValueError, match="COTIZACIONES_DB_POOL_SIZE"):
        Settings.from_environment()


@pytest.mark.parametrize("campo", ["topico_peticiones", "topico_registrada", "topico_rechazada"])
def test_topico_sin_prefijo_persistente_falla(campo: str) -> None:
    cambios: dict[str, Any] = {campo: "non-persistent://public/default/x"}
    with pytest.raises(ValueError, match="persistent://"):
        replace(Settings(), **cambios)


@pytest.mark.parametrize(
    ("campo", "copiado_de"),
    [
        ("topico_registrada", "topico_peticiones"),
        ("topico_rechazada", "topico_peticiones"),
        ("topico_rechazada", "topico_registrada"),
    ],
)
def test_topicos_repetidos_fallan(campo: str, copiado_de: str) -> None:
    base = Settings()
    with pytest.raises(ValueError, match="distintos"):
        replace(base, **{campo: getattr(base, copiado_de)})


@pytest.mark.parametrize("valor", ["", "   "])
def test_suscripcion_vacia_falla(valor: str) -> None:
    with pytest.raises(ValueError, match="suscripcion"):
        Settings(suscripcion_peticiones=valor)


@pytest.mark.parametrize(
    "campo",
    [
        "pool_size",
        "statement_timeout_ms",
        "pulsar_timeout_segundos",
        "receptor_cola",
        "demora_nack_ms",
    ],
)
@pytest.mark.parametrize("valor", [0, -1])
def test_pool_timeouts_y_cola_no_positivos_fallan(campo: str, valor: int) -> None:
    cambios: dict[str, Any] = {campo: valor}
    with pytest.raises(ValueError, match=campo):
        replace(Settings(), **cambios)


def test_desbordamiento_del_pool_admite_cero_pero_no_negativo() -> None:
    assert Settings(max_overflow=0).max_overflow == 0
    with pytest.raises(ValueError, match="max_overflow"):
        Settings(max_overflow=-1)


def test_retardo_de_laboratorio_negativo_falla() -> None:
    assert Settings(retardo_laboratorio_ms=0).retardo_laboratorio_ms == 0
    with pytest.raises(ValueError, match="retardo_laboratorio_ms"):
        Settings(retardo_laboratorio_ms=-1)
