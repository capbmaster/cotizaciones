from fastapi.testclient import TestClient

from cotizaciones.api.app import create_app
from cotizaciones.config.database import Database
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente

from ..unitarias.aplicacion.datos import comando_peticion
from ..unitarias.dominio.datos import ID_PETICION, uuid_lab
from .datos import procesar_sql
from .pulsar import LaboratorioPulsar

ID_PETICION_RECHAZO = uuid_lab("0041")


def test_comando_real_persistencia_y_consulta_http(
    base: Database, catalogo_v1: CatalogoVigente, laboratorio: LaboratorioPulsar
) -> None:
    procesar = procesar_sql(base)
    # F1: propuesta.
    propuesta = procesar(comando_peticion())
    # F5: rechazo (otra petición, otra categoría sin oferta en el catálogo).
    rechazo = procesar(
        comando_peticion(
            id_peticion=ID_PETICION_RECHAZO,
            origen={"id_comando": uuid_lab("0042")},
            categoria="jardineria",
        )
    )

    with TestClient(create_app(laboratorio.configuracion)) as cliente:
        respuesta = cliente.get(f"/cotizaciones/{propuesta.id_cotizacion}")
        assert respuesta.status_code == 200
        vista = respuesta.json()
        assert vista["estado"] == "PROPUESTA"
        assert vista["importe_menor"] == 15_000_000
        assert vista["motivo"] is None

        respuesta_rechazo = cliente.get(f"/cotizaciones/{rechazo.id_cotizacion}")
        assert respuesta_rechazo.status_code == 200
        vista_rechazo = respuesta_rechazo.json()
        assert vista_rechazo["estado"] == "RECHAZADA"
        assert vista_rechazo["motivo"] == "SIN_OFERTA_PARA_CATEGORIA"
        assert vista_rechazo["importe_menor"] is None

        listado = cliente.get("/cotizaciones", params={"id_peticion": str(ID_PETICION)})
        assert listado.status_code == 200
        assert len(listado.json()) == 1
        assert listado.json()[0]["id_cotizacion"] == str(propuesta.id_cotizacion)

    # Reabrir sobre la misma base: los datos persisten.
    with TestClient(create_app(laboratorio.configuracion)) as cliente:
        assert cliente.get(f"/cotizaciones/{propuesta.id_cotizacion}").status_code == 200
        assert cliente.get(f"/cotizaciones/{rechazo.id_cotizacion}").status_code == 200
