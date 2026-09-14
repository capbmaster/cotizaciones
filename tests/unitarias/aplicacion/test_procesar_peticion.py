from typing import Any, cast
from uuid import UUID

import pytest

from cotizaciones.config.bootstrap import componer_procesamiento
from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.aplicacion.excepciones import ConflictoPeticion
from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ProcesarPeticionHandler,
    ResultadoProcesamiento,
)
from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.eventos import (
    CotizacionRechazada,
    CotizacionRegistrada,
)
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoNoDisponible
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    EstadoCotizacion,
    MotivoRechazo,
    TipoRed,
)
from cotizaciones.seedwork.aplicacion.excepciones import ConflictoMensaje
from cotizaciones.seedwork.dominio.eventos import EventoDominio

from ..dominio.datos import (
    A101,
    A102,
    ID_COMANDO,
    INSTANTE_RESULTADO,
    PARTNER_SIN_HOMOLOGADOS,
    catalogo_laboratorio,
    datos_peticion,
    oferta,
    uuid_lab,
)
from .datos import comando_peticion
from .dobles.identificadores import IdentificadoresSecuenciales
from .dobles.reloj import RelojFijo
from .dobles.unidad_trabajo import (
    AlmacenMemoria,
    ConfirmacionAjena,
    EstadoMemoria,
    UnidadTrabajoMemoria,
)

CONSUMIDOR = ProcesarPeticionHandler.consumidor
# IdentificadoresSecuenciales entrega 100 para la cotización y 101 para su evento.
PRIMER_ID = UUID(int=100)
PRIMER_EVENTO = UUID(int=101)
OTRO_COMANDO = uuid_lab("0023")
GENERAL = TipoRed.GENERAL_HDA
HOMOLOGADA = TipoRed.HOMOLOGADA_PARTNER


def preparar(
    catalogo: CatalogoVigente | None,
) -> tuple[AlmacenMemoria, ProcesarPeticionHandler]:
    almacen = AlmacenMemoria(EstadoMemoria(catalogo=catalogo))
    procesar = componer_procesamiento(
        lambda: UnidadTrabajoMemoria(almacen), RelojFijo(), IdentificadoresSecuenciales()
    )
    return almacen, procesar


def sin_escrituras(almacen: AlmacenMemoria) -> bool:
    estado = almacen.estado
    return (
        estado.cotizaciones == {}
        and estado.recepciones == {}
        and estado.salidas == []
        and almacen.confirmaciones == 0
    )


def test_el_consumidor_del_inbox_tiene_el_nombre_del_contrato() -> None:
    assert CONSUMIDOR == "cotizaciones.procesar_peticion"


def test_el_comando_propio_solo_admite_tipos_de_dominio() -> None:
    with pytest.raises(ValueError):
        ProcesarPeticionCotizacion(origen=cast(Any, "comando"), datos=datos_peticion())
    with pytest.raises(ValueError):
        ProcesarPeticionCotizacion(
            origen=comando_peticion().origen, datos=cast(Any, {"id_peticion": "x"})
        )


def test_los_conflictos_son_errores_de_validacion() -> None:
    assert issubclass(ConflictoPeticion, ValueError)
    assert issubclass(ConflictoMensaje, ValueError)


@pytest.mark.parametrize(
    ("cambios", "tipo_salida", "estado"),
    [
        pytest.param({}, CotizacionRegistrada, EstadoCotizacion.PROPUESTA, id="F1"),
        pytest.param(
            {"tipo_red": HOMOLOGADA}, CotizacionRegistrada, EstadoCotizacion.PROPUESTA, id="F2"
        ),
        pytest.param(
            {"tipo_red": HOMOLOGADA, "id_partner": PARTNER_SIN_HOMOLOGADOS},
            CotizacionRechazada,
            EstadoCotizacion.RECHAZADA,
            id="F3",
        ),
        pytest.param(
            {"categoria": "electricidad", "tipo_red": HOMOLOGADA},
            CotizacionRechazada,
            EstadoCotizacion.RECHAZADA,
            id="F4",
        ),
        pytest.param(
            {"categoria": "jardineria"},
            CotizacionRechazada,
            EstadoCotizacion.RECHAZADA,
            id="F5",
        ),
    ],
)
def test_peticion_nueva_deja_una_cotizacion_una_marca_y_una_salida(
    cambios: dict[str, Any], tipo_salida: type[EventoDominio], estado: EstadoCotizacion
) -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    resultado = procesar(comando_peticion(**cambios))
    assert resultado == ResultadoProcesamiento(id_cotizacion=PRIMER_ID, nueva=True)
    (cotizacion,) = almacen.estado.cotizaciones.values()
    assert cotizacion.id == PRIMER_ID
    assert cotizacion.estado is estado
    assert cotizacion.resuelta_en == INSTANTE_RESULTADO
    assert cotizacion.eventos_pendientes == ()
    assert list(almacen.estado.recepciones) == [(CONSUMIDOR, ID_COMANDO)]
    (salida,) = almacen.estado.salidas
    assert isinstance(salida, tipo_salida)
    assert salida.id_evento == PRIMER_EVENTO
    assert almacen.confirmaciones == 1


def test_catalogo_ausente_no_deja_cotizacion_inbox_ni_salida_y_se_puede_reintentar() -> None:
    almacen, procesar = preparar(None)
    with pytest.raises(CatalogoNoDisponible):
        procesar(comando_peticion())
    assert sin_escrituras(almacen)
    # Como el inbox también se revirtió, la reentrega se procesa cuando el catálogo existe.
    almacen.estado.catalogo = catalogo_laboratorio()
    assert procesar(comando_peticion()).nueva is True
    assert len(almacen.estado.cotizaciones) == 1


def test_fallo_al_registrar_la_salida_no_deja_cotizacion_ni_marca() -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    almacen.fallar_al_registrar_salida = True
    with pytest.raises(RuntimeError, match="salida"):
        procesar(comando_peticion())
    assert sin_escrituras(almacen)


def test_fallo_al_guardar_la_cotizacion_no_deja_marca_ni_salida() -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    almacen.fallar_al_guardar = True
    with pytest.raises(RuntimeError, match="guardar"):
        procesar(comando_peticion())
    assert sin_escrituras(almacen)


def test_rechazo_valido_confirma_inbox_y_salida() -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    resultado = procesar(comando_peticion(categoria="jardineria"))
    assert resultado.nueva is True
    (salida,) = almacen.estado.salidas
    assert isinstance(salida, CotizacionRechazada)
    assert salida.motivo is MotivoRechazo.SIN_OFERTA_PARA_CATEGORIA
    assert list(almacen.estado.recepciones) == [(CONSUMIDOR, ID_COMANDO)]
    assert almacen.confirmaciones == 1


def test_el_mismo_comando_dos_veces_no_crea_otra_salida() -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    primero = procesar(comando_peticion())
    segundo = procesar(comando_peticion())
    assert primero == ResultadoProcesamiento(id_cotizacion=PRIMER_ID, nueva=True)
    assert segundo == ResultadoProcesamiento(id_cotizacion=PRIMER_ID, nueva=False)
    assert len(almacen.estado.cotizaciones) == 1
    assert len(almacen.estado.recepciones) == 1
    assert len(almacen.estado.salidas) == 1
    assert almacen.confirmaciones == 1
    assert almacen.consultas_catalogo == 1


def test_otro_comando_con_los_mismos_datos_solo_agrega_su_marca() -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    procesar(comando_peticion())
    segundo = procesar(comando_peticion(origen={"id_comando": OTRO_COMANDO}))
    assert segundo == ResultadoProcesamiento(id_cotizacion=PRIMER_ID, nueva=False)
    assert set(almacen.estado.recepciones) == {
        (CONSUMIDOR, ID_COMANDO),
        (CONSUMIDOR, OTRO_COMANDO),
    }
    assert len(almacen.estado.cotizaciones) == 1
    (salida,) = almacen.estado.salidas
    assert salida.id_evento == PRIMER_EVENTO
    assert almacen.confirmaciones == 2
    assert almacen.consultas_catalogo == 1


def test_cambio_de_catalogo_entre_entregas_devuelve_la_resolucion_original() -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    procesar(comando_peticion())
    almacen.estado.catalogo = CatalogoVigente(
        version=2, ofertas=(oferta(A102, "plomeria", GENERAL, None, 11_000_000),)
    )
    segundo = procesar(comando_peticion(origen={"id_comando": OTRO_COMANDO}))
    assert segundo.id_cotizacion == PRIMER_ID
    (cotizacion,) = almacen.estado.cotizaciones.values()
    assert cotizacion.version_catalogo == 1
    assert cotizacion.resultado.oferta is not None
    assert cotizacion.resultado.oferta.id_proveedor == A101
    assert len(almacen.estado.salidas) == 1


@pytest.mark.parametrize(
    "cambios",
    [
        pytest.param({"categoria": "electricidad"}, id="otra-categoria"),
        pytest.param({"tipo_red": HOMOLOGADA}, id="otra-red"),
        pytest.param({"id_trabajo": uuid_lab("0099")}, id="otro-trabajo"),
    ],
)
def test_misma_peticion_con_otros_datos_es_conflicto_y_no_escribe(
    cambios: dict[str, Any],
) -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    procesar(comando_peticion())
    original = almacen.estado.cotizaciones.copy()
    with pytest.raises(ConflictoPeticion):
        procesar(comando_peticion(origen={"id_comando": OTRO_COMANDO}, **cambios))
    assert almacen.estado.cotizaciones == original
    assert list(almacen.estado.recepciones) == [(CONSUMIDOR, ID_COMANDO)]
    assert len(almacen.estado.salidas) == 1
    assert almacen.confirmaciones == 1


def test_mismo_comando_con_otra_peticion_es_conflicto_de_mensaje() -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    procesar(comando_peticion())
    with pytest.raises(ConflictoMensaje):
        procesar(comando_peticion(id_peticion=uuid_lab("0025")))
    assert len(almacen.estado.cotizaciones) == 1
    assert len(almacen.estado.salidas) == 1
    assert almacen.confirmaciones == 1
    assert almacen.consultas_catalogo == 1


def test_colision_en_el_primer_intento_reutiliza_la_cotizacion_de_la_otra_replica() -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    comando_ajeno = comando_peticion(origen={"id_comando": uuid_lab("0500")})
    cotizacion_ajena = Cotizacion.resolver(
        id=uuid_lab("0600"),
        peticion=comando_ajeno.datos,
        origen=comando_ajeno.origen,
        catalogo=catalogo_laboratorio(),
        id_evento=uuid_lab("0601"),
        instante=INSTANTE_RESULTADO,
    )
    almacen.colision_con = ConfirmacionAjena(CONSUMIDOR, comando_ajeno, cotizacion_ajena)

    resultado = procesar(comando_peticion())

    assert resultado == ResultadoProcesamiento(id_cotizacion=uuid_lab("0600"), nueva=False)
    assert almacen.aperturas == 2
    assert list(almacen.estado.cotizaciones.values()) == [cotizacion_ajena]
    assert set(almacen.estado.recepciones) == {
        (CONSUMIDOR, uuid_lab("0500")),
        (CONSUMIDOR, ID_COMANDO),
    }
    (salida,) = almacen.estado.salidas
    assert salida.id_evento == uuid_lab("0601")


def test_marca_sin_cotizacion_termina_sin_efecto_ni_lectura_de_catalogo() -> None:
    almacen, procesar = preparar(catalogo_laboratorio())
    comando = comando_peticion()
    almacen.estado.recepciones[(CONSUMIDOR, ID_COMANDO)] = comando
    assert procesar(comando) == ResultadoProcesamiento(id_cotizacion=None, nueva=False)
    assert almacen.estado.cotizaciones == {}
    assert almacen.estado.salidas == []
    assert almacen.confirmaciones == 0
    assert almacen.consultas_catalogo == 0
