from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from cotizaciones.api.app import create_app
from cotizaciones.api.cotizaciones import obtener_consulta, obtener_listado
from cotizaciones.config.database import Database
from cotizaciones.config.procesamiento import EstadoMensajeria
from cotizaciones.config.settings import Settings
from cotizaciones.modulos.cotizaciones.aplicacion.consultas import FiltroCotizaciones

from ..unitarias.dominio.datos import A101, ID_COTIZACION, ID_PETICION, cotizacion_resuelta
from ..unitarias.dominio.datos import INSTANTE_RESULTADO as INSTANTE

VISTA = cotizacion_resuelta()


def vista_http() -> dict[str, object]:
    return {
        "id_cotizacion": str(ID_COTIZACION),
        "id_peticion": str(ID_PETICION),
        "id_trabajo": str(VISTA.peticion.id_trabajo),
        "id_solicitud": str(VISTA.peticion.id_solicitud),
        "id_partner": str(VISTA.peticion.id_partner),
        "categoria": "plomeria",
        "tipo_solicitud": "SINIESTRO",
        "tipo_red": "GENERAL_HDA",
        "estado": "PROPUESTA",
        "id_proveedor": str(A101),
        "importe_menor": 15_000_000,
        "moneda": "COP",
        "motivo": None,
        "version_catalogo": 1,
        "version_cotizacion": 1,
        "id_comando_origen": str(VISTA.origen.id_comando),
        "resuelta_en": "2026-09-12T15:00:04Z",
        "duracion_estimada_minutos": None,
    }


@asynccontextmanager
async def _sin_procesamiento(
    base: Database, configuracion: Settings
) -> AsyncIterator[EstadoMensajeria]:
    yield EstadoMensajeria()


@pytest.fixture
def api() -> Iterator[tuple[TestClient, Mock, Mock]]:
    consulta = Mock(return_value=None)
    listado = Mock(return_value=[])
    base_doble = Mock(spec=Database)
    app = create_app(
        Settings(database_url="postgresql+psycopg://x@x/x"),
        database_factory=lambda _configuracion: base_doble,
        processing_factory=_sin_procesamiento,
    )
    app.dependency_overrides[obtener_consulta] = lambda: consulta
    app.dependency_overrides[obtener_listado] = lambda: listado
    with TestClient(app) as cliente:
        yield cliente, consulta, listado


def test_consulta_por_id_devuelve_200_con_la_vista(
    api: tuple[TestClient, Mock, Mock],
) -> None:
    cliente, consulta, _ = api
    consulta.return_value = _vista_dominio_a_dto()
    respuesta = cliente.get(f"/cotizaciones/{ID_COTIZACION}")
    assert respuesta.status_code == 200
    assert respuesta.json() == vista_http()
    consulta.assert_called_once_with(ID_COTIZACION)


def test_consulta_ausente_devuelve_404(api: tuple[TestClient, Mock, Mock]) -> None:
    cliente, _, _ = api
    respuesta = cliente.get(f"/cotizaciones/{ID_COTIZACION}")
    assert respuesta.status_code == 404


def test_id_invalido_devuelve_422(api: tuple[TestClient, Mock, Mock]) -> None:
    cliente, consulta, _ = api
    respuesta = cliente.get("/cotizaciones/no-es-un-uuid")
    assert respuesta.status_code == 422
    consulta.assert_not_called()


def test_limite_fuera_de_rango_devuelve_422(api: tuple[TestClient, Mock, Mock]) -> None:
    cliente, _, listado = api
    assert cliente.get("/cotizaciones", params={"limite": 0}).status_code == 422
    assert cliente.get("/cotizaciones", params={"limite": 101}).status_code == 422
    assert cliente.get("/cotizaciones", params={"desplazamiento": -1}).status_code == 422
    listado.assert_not_called()


def test_listado_combina_filtros_y_pasa_al_handler(api: tuple[TestClient, Mock, Mock]) -> None:
    cliente, _, listado = api
    respuesta = cliente.get(
        "/cotizaciones",
        params={"id_peticion": str(ID_PETICION), "estado": "PROPUESTA", "limite": 5},
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == []
    filtro, limite, desplazamiento = listado.call_args.args
    assert filtro == FiltroCotizaciones(
        id_peticion=ID_PETICION, estado=VISTA.estado, id_trabajo=None
    )
    assert limite == 5
    assert desplazamiento == 0


def test_sin_base_responde_503() -> None:
    with TestClient(create_app(Settings())) as cliente:
        assert cliente.get(f"/cotizaciones/{ID_COTIZACION}").status_code == 503
        assert cliente.get("/cotizaciones").status_code == 503


def _vista_dominio_a_dto() -> object:
    from cotizaciones.modulos.cotizaciones.aplicacion.consultas import VistaCotizacion

    return VistaCotizacion(
        id_cotizacion=ID_COTIZACION,
        id_peticion=VISTA.peticion.id_peticion,
        id_trabajo=VISTA.peticion.id_trabajo,
        id_solicitud=VISTA.peticion.id_solicitud,
        id_partner=VISTA.peticion.id_partner,
        categoria=VISTA.peticion.categoria,
        tipo_solicitud=VISTA.peticion.tipo_solicitud,
        tipo_red=VISTA.peticion.tipo_red,
        estado=VISTA.estado,
        id_proveedor=A101,
        importe_menor=15_000_000,
        moneda="COP",
        motivo=None,
        version_catalogo=1,
        version_cotizacion=1,
        id_comando_origen=VISTA.origen.id_comando,
        resuelta_en=INSTANTE,
    )
