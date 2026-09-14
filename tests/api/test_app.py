import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from cotizaciones.api.app import create_app, get_settings
from cotizaciones.config.database import Database
from cotizaciones.config.settings import Settings
from cotizaciones.infraestructura.ciclo_vida import EstadoMensajeria
from cotizaciones.seedwork.aplicacion.excepciones import ColisionPersistencia
from cotizaciones.seedwork.infraestructura.ciclos import EstadoCiclo, EstadoComponente

CON_BASE = Settings(database_url="postgresql+psycopg://prueba:prueba@db:5432/prueba")


def base_doble(disponible: bool = True) -> Mock:
    base = Mock(spec=Database)
    base.verificar.return_value = disponible
    return base


class ProcesamientoFalso:
    def __init__(
        self, estado: EstadoMensajeria | None = None, eventos: list[str] | None = None
    ) -> None:
        self.estado = estado if estado is not None else EstadoMensajeria()
        self.eventos = eventos if eventos is not None else []
        self.entradas = 0
        self.salidas = 0
        self.recibido: list[tuple[Database, Settings]] = []

    @asynccontextmanager
    async def __call__(
        self, base: Database, configuracion: Settings
    ) -> AsyncIterator[EstadoMensajeria]:
        self.entradas += 1
        self.recibido.append((base, configuracion))
        try:
            yield self.estado
        finally:
            self.salidas += 1
            self.eventos.append("mensajeria cerrada")


def test_titulo_de_la_aplicacion() -> None:
    assert create_app(Settings()).title == "Cotizaciones"


def test_sin_settings_lee_el_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COTIZACIONES_DATABASE_URL", raising=False)
    monkeypatch.setenv("COTIZACIONES_SERVICE_NAME", "cotizaciones-entorno")
    with TestClient(create_app()) as cliente:
        assert cliente.get("/health/live").json()["service"] == "cotizaciones-entorno"


def test_sin_base_live_responde_y_ready_informa_base_no_configurada() -> None:
    fabrica_base = Mock(side_effect=AssertionError("base no configurada"))
    procesamiento = Mock(side_effect=AssertionError("mensajeria sin base"))
    with TestClient(create_app(Settings(), fabrica_base, procesamiento)) as cliente:
        live = cliente.get("/health/live")
        ready = cliente.get("/health/ready")
    assert live.status_code == 200
    assert live.json() == {"status": "ok", "service": "cotizaciones"}
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "no_listo",
        "motivo": "base_no_configurada",
        "componentes": {},
    }
    fabrica_base.assert_not_called()
    procesamiento.assert_not_called()


def test_ready_con_base_disponible_y_mensajeria_lista_verifica_fuera_del_event_loop() -> None:
    en_event_loop: list[bool] = []

    def verificar() -> bool:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            en_event_loop.append(False)
        else:
            en_event_loop.append(True)
        return True

    base = base_doble()
    base.verificar.side_effect = verificar
    fabrica = Mock(return_value=base)
    operando = EstadoComponente("consumo-peticiones", EstadoCiclo.OPERANDO)
    procesamiento = ProcesamientoFalso(EstadoMensajeria((operando,)))
    aplicacion = create_app(CON_BASE, fabrica, procesamiento)
    with TestClient(aplicacion) as cliente:
        respuesta = cliente.get("/health/ready")
        assert aplicacion.state.database is base
        assert aplicacion.state.estado_mensajeria is procesamiento.estado
    assert respuesta.status_code == 200
    assert respuesta.json() == {
        "status": "listo",
        "componentes": {
            "consumo-peticiones": {
                "estado": "OPERANDO",
                "ultimo_error": None,
                "id_mensaje_pausa": None,
                "motivo_pausa": None,
                "ultimo_exito": None,
            }
        },
    }
    fabrica.assert_called_once_with(CON_BASE)
    assert procesamiento.recibido == [(base, CON_BASE)]
    assert en_event_loop == [False]


def test_ready_informa_base_no_disponible() -> None:
    aplicacion = create_app(CON_BASE, Mock(return_value=base_doble(False)), ProcesamientoFalso())
    with TestClient(aplicacion) as cliente:
        respuesta = cliente.get("/health/ready")
    assert respuesta.status_code == 503
    assert respuesta.json()["status"] == "no_listo"
    assert respuesta.json()["motivo"] == "base_no_disponible"


def test_ready_informa_mensajeria_no_operativa_con_la_pausa() -> None:
    pausado = EstadoComponente(
        "consumo-peticiones",
        EstadoCiclo.PAUSADO,
        ultimo_error="ComandoInvalido: categoria vacia",
        id_mensaje_pausa="00000000-0000-0000-0000-000000000022",
        motivo_pausa="categoria vacia",
    )
    despacho = EstadoComponente("despacho-resultados", EstadoCiclo.OPERANDO)
    procesamiento = ProcesamientoFalso(EstadoMensajeria((pausado, despacho)))
    aplicacion = create_app(CON_BASE, Mock(return_value=base_doble()), procesamiento)
    with TestClient(aplicacion) as cliente:
        respuesta = cliente.get("/health/ready")
    assert respuesta.status_code == 503
    assert respuesta.json() == {
        "status": "no_listo",
        "motivo": "mensajeria_no_operativa",
        "componentes": {
            "consumo-peticiones": {
                "estado": "PAUSADO",
                "ultimo_error": "ComandoInvalido: categoria vacia",
                "id_mensaje_pausa": "00000000-0000-0000-0000-000000000022",
                "motivo_pausa": "categoria vacia",
                "ultimo_exito": None,
            },
            "despacho-resultados": {
                "estado": "OPERANDO",
                "ultimo_error": None,
                "id_mensaje_pausa": None,
                "motivo_pausa": None,
                "ultimo_exito": None,
            },
        },
    }


def test_entrar_y_salir_dos_veces_cierra_base_y_mensajeria_dos_veces() -> None:
    base = base_doble()
    procesamiento = ProcesamientoFalso()
    aplicacion = create_app(CON_BASE, Mock(return_value=base), procesamiento)
    for _ in range(2):
        with TestClient(aplicacion) as cliente:
            assert cliente.get("/health/ready").status_code == 200
    assert procesamiento.entradas == 2
    assert procesamiento.salidas == 2
    assert base.close.call_count == 2
    assert aplicacion.state.database is None
    assert aplicacion.state.estado_mensajeria is None


@pytest.mark.parametrize("con_error", [False, True])
def test_cierra_mensajeria_antes_que_la_base_incluso_ante_error(con_error: bool) -> None:
    eventos: list[str] = []
    base = base_doble()
    base.close.side_effect = lambda: eventos.append("base cerrada")
    aplicacion = create_app(CON_BASE, Mock(return_value=base), ProcesamientoFalso(eventos=eventos))

    def ejercitar() -> None:
        with TestClient(aplicacion):
            assert eventos == []
            if con_error:
                raise RuntimeError("fallo de operacion")

    if con_error:
        with pytest.raises(RuntimeError, match="fallo de operacion"):
            ejercitar()
    else:
        ejercitar()
    assert eventos == ["mensajeria cerrada", "base cerrada"]


def test_fallo_al_iniciar_la_mensajeria_cierra_la_base() -> None:
    base = base_doble()
    procesamiento = Mock(side_effect=RuntimeError("arranque de mensajeria fallido"))
    aplicacion = create_app(CON_BASE, Mock(return_value=base), procesamiento)
    with pytest.raises(RuntimeError, match="arranque de mensajeria fallido"):
        with TestClient(aplicacion):
            pass
    base.close.assert_called_once_with()
    assert aplicacion.state.database is None


def test_recursos_de_base_no_se_comparten_entre_aplicaciones() -> None:
    primera, segunda = base_doble(), base_doble()
    fabrica = Mock(side_effect=[primera, segunda])
    primera_app = create_app(CON_BASE, fabrica, ProcesamientoFalso())
    segunda_app = create_app(CON_BASE, fabrica, ProcesamientoFalso())
    with TestClient(primera_app), TestClient(segunda_app):
        assert primera_app.state.database is primera
        assert segunda_app.state.database is segunda
    primera.close.assert_called_once_with()
    segunda.close.assert_called_once_with()


def test_overrides_aislados_por_aplicacion() -> None:
    primera = create_app(Settings(service_name="primera"))
    segunda = create_app(Settings(service_name="segunda"))
    primera.dependency_overrides[get_settings] = lambda: Settings(service_name="sustituida")
    try:
        with TestClient(primera) as cliente_1, TestClient(segunda) as cliente_2:
            assert cliente_1.get("/health/live").json()["service"] == "sustituida"
            assert cliente_2.get("/health/live").json()["service"] == "segunda"
    finally:
        primera.dependency_overrides.clear()
    assert segunda.dependency_overrides == {}


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("base caida")),
        ColisionPersistencia("carrera en uq_cotizacion_peticion"),
    ],
)
def test_errores_de_persistencia_responden_503(error: Exception) -> None:
    aplicacion = create_app(Settings())

    def fallar() -> None:
        raise error

    aplicacion.add_api_route("/prueba-fallo", fallar)
    with TestClient(aplicacion) as cliente:
        respuesta = cliente.get("/prueba-fallo")
    assert respuesta.status_code == 503
    assert respuesta.json() == {"detail": "Persistencia temporalmente no disponible"}
