from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text

from cotizaciones.config.database import Database
from cotizaciones.config.persistencia import crear_uow_cotizaciones
from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoInvalido
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    EstadoCotizacion,
    ResultadoCotizacion,
    TipoRed,
)
from cotizaciones.modulos.cotizaciones.infraestructura.orm import CotizacionSQL, OfertaCatalogoSQL
from cotizaciones.modulos.cotizaciones.infraestructura.repositorios import id_oferta

from ..unitarias.dominio.datos import (
    A101,
    INSTANTE_COMANDO,
    PARTNER_SIN_HOMOLOGADOS,
    catalogo_laboratorio,
    cotizacion_resuelta,
    oferta,
    uuid_lab,
)
from .datos import registrar_catalogo

CAMPOS = (
    "id",
    "peticion",
    "origen",
    "version_catalogo",
    "version_cotizacion",
    "resultado",
    "resuelta_en",
)


def guardar(base: Database, cotizacion: Cotizacion) -> None:
    with crear_uow_cotizaciones(base) as unidad:
        unidad.cotizaciones.guardar(cotizacion)
        unidad.confirmar()


def recuperar(base: Database, id_peticion: UUID) -> Cotizacion | None:
    base.engine.dispose()
    with crear_uow_cotizaciones(base) as unidad:
        return unidad.cotizaciones.obtener_por_peticion(id_peticion)


@pytest.mark.parametrize(
    "cambios",
    [
        pytest.param({}, id="F1"),
        pytest.param({"tipo_red": TipoRed.HOMOLOGADA_PARTNER}, id="F2"),
        pytest.param(
            {"tipo_red": TipoRed.HOMOLOGADA_PARTNER, "id_partner": PARTNER_SIN_HOMOLOGADOS},
            id="F3",
        ),
        pytest.param({"categoria": "jardineria"}, id="F5"),
        pytest.param({"categoria": "  Plomeria "}, id="F6"),
    ],
)
def test_ida_y_vuelta_exacta_de_propuestas_y_rechazos(
    base: Database, catalogo_v1: CatalogoVigente, cambios: dict[str, Any]
) -> None:
    original = cotizacion_resuelta(**cambios)
    original.retirar_eventos()
    guardar(base, original)
    recuperada = recuperar(base, original.peticion.id_peticion)
    assert recuperada is not None
    for campo in CAMPOS:
        assert getattr(recuperada, campo) == getattr(original, campo), campo
    assert recuperada.eventos_pendientes == ()


def test_el_importe_conserva_su_valor_entero_exacto(
    base: Database, catalogo_v1: CatalogoVigente
) -> None:
    grande = 2**53 + 1
    original = replace(
        cotizacion_resuelta(),
        resultado=ResultadoCotizacion(
            estado=EstadoCotizacion.PROPUESTA,
            oferta=oferta(A101, "plomeria", TipoRed.GENERAL_HDA, None, grande),
        ),
    )
    guardar(base, original)
    recuperada = recuperar(base, original.peticion.id_peticion)
    assert recuperada is not None and recuperada.resultado.oferta is not None
    assert recuperada.resultado.oferta.precio.importe_menor == grande
    with base.engine.connect() as conexion:
        assert (
            conexion.scalar(text("SELECT importe_menor FROM cotizaciones.cotizaciones")) == grande
        )


def test_columnas_de_la_fila(base: Database, catalogo_v1: CatalogoVigente) -> None:
    original = cotizacion_resuelta()
    guardar(base, original)
    with base.session_factory() as sesion:
        fila = sesion.scalar(select(CotizacionSQL))
    assert fila is not None
    assert fila.id == original.id
    assert fila.id_peticion == original.peticion.id_peticion
    assert fila.id_trabajo == original.peticion.id_trabajo
    assert fila.estado == "PROPUESTA"
    assert fila.id_proveedor == A101
    assert fila.importe_menor == 15_000_000
    assert fila.moneda == "COP"
    assert fila.motivo is None
    assert fila.peticion["categoria"] == "plomeria"
    assert fila.instante_comando == INSTANTE_COMANDO
    assert fila.registrada_en is not None


def test_peticion_sin_cotizacion_devuelve_none(base: Database) -> None:
    assert recuperar(base, uuid_lab("0099")) is None


def test_catalogo_vigente_ida_y_vuelta_ordenado_por_proveedor(
    base: Database, catalogo_v1: CatalogoVigente
) -> None:
    with crear_uow_cotizaciones(base) as unidad:
        vigente = unidad.catalogos.obtener_vigente()
    assert vigente is not None
    assert vigente.version == 1
    assert set(vigente.ofertas) == set(catalogo_v1.ofertas)
    proveedores = [str(o.id_proveedor) for o in vigente.ofertas]
    assert proveedores == sorted(proveedores)


def test_version_registrada_sin_activar_no_es_vigente(base: Database) -> None:
    registrar_catalogo(base, catalogo_laboratorio(), activar=False)
    with crear_uow_cotizaciones(base) as unidad:
        assert unidad.catalogos.obtener_vigente() is None


def test_filas_de_catalogo_invalidas_lanzan_catalogo_invalido(base: Database) -> None:
    with base.engine.begin() as conexion:
        conexion.execute(
            text(
                "INSERT INTO cotizaciones.catalogos (version, huella, activo) VALUES (1, 'x', true)"
            )
        )
        conexion.execute(
            text(
                "INSERT INTO cotizaciones.ofertas_catalogo (id, version_catalogo, id_proveedor, "
                "categoria, tipo_red, id_partner, importe_menor, moneda) VALUES "
                "(gen_random_uuid(), 1, gen_random_uuid(), 'Plomeria', 'GENERAL_HDA', NULL, 1, "
                "'COP')"
            )
        )
    with pytest.raises(CatalogoInvalido), crear_uow_cotizaciones(base) as unidad:
        unidad.catalogos.obtener_vigente()


def test_el_id_de_cada_oferta_es_determinista(base: Database, catalogo_v1: CatalogoVigente) -> None:
    with base.session_factory() as sesion:
        ids = set(sesion.scalars(select(OfertaCatalogoSQL.id)))
    assert ids == {id_oferta(1, o) for o in catalogo_v1.ofertas}
    primera = catalogo_v1.ofertas[0]
    assert id_oferta(1, primera) == id_oferta(1, primera)
    assert id_oferta(2, primera) != id_oferta(1, primera)


# --- Paso 54 (E3): duracion_estimada_minutos persiste en la fila y en el catalogo ---


@pytest.mark.parametrize("duracion", [30, 90, None])
def test_ida_y_vuelta_de_la_duracion_estimada_en_la_cotizacion(
    base: Database, catalogo_v1: CatalogoVigente, duracion: int | None
) -> None:
    original = cotizacion_resuelta()
    oferta_elegida = original.resultado.oferta
    assert oferta_elegida is not None
    original = replace(
        original,
        resultado=ResultadoCotizacion(
            estado=EstadoCotizacion.PROPUESTA,
            oferta=replace(oferta_elegida, duracion_estimada_minutos=duracion),
        ),
    )
    guardar(base, original)
    recuperada = recuperar(base, original.peticion.id_peticion)
    assert recuperada is not None and recuperada.resultado.oferta is not None
    assert recuperada.resultado.oferta.duracion_estimada_minutos == duracion
    with base.engine.connect() as conexion:
        valor = conexion.scalar(
            text("SELECT duracion_estimada_minutos FROM cotizaciones.cotizaciones")
        )
    assert valor == duracion


def test_fila_previa_a_la_migracion_se_lee_con_duracion_nula(
    base: Database, catalogo_v1: CatalogoVigente
) -> None:
    """Una fila insertada sin la columna (como quedan las v1 tras el ALTER) lee duracion None."""
    guardar(base, cotizacion_resuelta())
    with base.engine.begin() as conexion:
        conexion.execute(
            text(
                "UPDATE cotizaciones.cotizaciones SET duracion_estimada_minutos = NULL "
                "WHERE id_peticion = :id_peticion"
            ),
            {"id_peticion": str(cotizacion_resuelta().peticion.id_peticion)},
        )
    recuperada = recuperar(base, cotizacion_resuelta().peticion.id_peticion)
    assert recuperada is not None and recuperada.resultado.oferta is not None
    assert recuperada.resultado.oferta.duracion_estimada_minutos is None


def test_ida_y_vuelta_de_la_duracion_en_el_catalogo(base: Database) -> None:
    catalogo_con_duracion = CatalogoVigente(
        version=2,
        ofertas=(
            replace(
                oferta(A101, "plomeria", TipoRed.GENERAL_HDA, None, 1), duracion_estimada_minutos=30
            ),
        ),
    )
    registrar_catalogo(base, catalogo_con_duracion)
    with crear_uow_cotizaciones(base) as unidad:
        vigente = unidad.catalogos.obtener_vigente()
    assert vigente is not None
    assert vigente.ofertas[0].duracion_estimada_minutos == 30
