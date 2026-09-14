from typing import Any
from uuid import UUID

import pytest

from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import TipoRed, TipoSolicitud
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
    ComandoInvalido,
    comando_desde_mensaje,
    mensaje_rechazada,
    mensaje_registrada,
)
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import serializar_evento
from cotizaciones.seedwork.infraestructura.serializacion import Documento

from .aplicacion.datos import MENSAJE_COMANDO_F1, comando_peticion
from .dominio.datos import (
    A101,
    B101,
    ID_COMANDO,
    ID_COTIZACION,
    ID_EVENTO,
    ID_PETICION,
    ID_SOLICITUD,
    ID_TRABAJO,
    PARTNER_LAB,
    cotizacion_resuelta,
)

NULO = str(UUID(int=0))


def mensaje(**cambios: Any) -> Any:
    return SolicitarCotizacionV1(**{**MENSAJE_COMANDO_F1, **cambios})


def documento(**cambios_peticion: Any) -> Documento:
    (evento,) = cotizacion_resuelta(**cambios_peticion).retirar_eventos()
    return serializar_evento(evento)


def test_comando_invalido_es_un_error_de_validacion() -> None:
    assert issubclass(ComandoInvalido, ValueError)


def test_traduccion_valida_a_tipos_propios() -> None:
    assert comando_desde_mensaje(mensaje()) == comando_peticion()


def test_version_de_contrato_mayor_se_acepta_sin_igualdad_estricta() -> None:
    assert comando_desde_mensaje(mensaje(version_contrato=2)) == comando_peticion()


def test_homologada_e_instalacion_conservan_sus_valores() -> None:
    comando = comando_desde_mensaje(
        mensaje(tipo_red="HOMOLOGADA_PARTNER", tipo_solicitud="INSTALACION", categoria=" Plomeria")
    )
    assert comando.datos.tipo_red is TipoRed.HOMOLOGADA_PARTNER
    assert comando.datos.tipo_solicitud is TipoSolicitud.INSTALACION
    assert comando.datos.categoria == " Plomeria"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("command_id", ""),
        ("command_id", "no-es-uuid"),
        ("command_id", NULO),
        ("tipo", "SolicitarCotizacion.v2"),
        ("tipo", "CotizacionRegistrada.v1"),
        ("version_contrato", 0),
        ("version_contrato", -1),
        ("instante", "2026-09-12T15:00:03"),
        ("instante", "ayer"),
        ("correlacion", str(UUID(int=99))),
        ("correlacion", "no-es-uuid"),
        ("causacion", "no-es-uuid"),
        ("causacion", NULO),
        ("id_peticion", NULO),
        ("id_trabajo", "no-es-uuid"),
        ("id_solicitud", NULO),
        ("id_partner", NULO),
        ("categoria", ""),
        ("categoria", "   "),
        ("tipo_solicitud", "OTRA"),
        ("tipo_solicitud", "siniestro"),
        ("tipo_red", "OTRA_RED"),
        ("id_politica", NULO),
        ("version_politica", 0),
    ],
)
def test_cada_regla_violada_es_comando_invalido_con_el_campo(campo: str, valor: Any) -> None:
    with pytest.raises(ComandoInvalido, match=campo):
        comando_desde_mensaje(mensaje(**{campo: valor}))


def test_un_objeto_sin_los_campos_es_comando_invalido() -> None:
    with pytest.raises(ComandoInvalido, match="tipo"):
        comando_desde_mensaje(object())


def test_propuesta_a_record_v2() -> None:
    """Desde el Paso 56 el escritor publica el Record v2 (version_contrato=2)."""
    record = mensaje_registrada(documento())
    assert record.event_id == str(ID_EVENTO)
    assert record.tipo == "CotizacionRegistrada.v1"
    assert record.version_contrato == 2
    assert record.instante == "2026-09-12T15:00:04+00:00"
    assert record.correlacion == str(ID_SOLICITUD)
    assert record.causacion == str(ID_COMANDO)
    assert record.id_peticion == str(ID_PETICION)
    assert record.id_trabajo == str(ID_TRABAJO)
    assert record.id_partner == str(PARTNER_LAB)
    assert record.version_catalogo == 1
    assert record.version_cotizacion == 1
    assert record.id_cotizacion == str(ID_COTIZACION)
    assert record.id_proveedor == str(A101)
    assert record.importe_menor == 15_000_000
    assert record.moneda == "COP"
    assert record.categoria == "plomeria"
    assert record.tipo_red == "GENERAL_HDA"
    assert record.duracion_estimada_minutos is None


def test_la_categoria_se_publica_tal_como_llego() -> None:
    assert mensaje_registrada(documento(categoria="  Plomeria ")).categoria == "  Plomeria "


def test_la_propuesta_homologada_conserva_red_y_proveedor() -> None:
    record = mensaje_registrada(documento(tipo_red=TipoRed.HOMOLOGADA_PARTNER))
    assert record.tipo_red == "HOMOLOGADA_PARTNER"
    assert record.id_proveedor == str(B101)
    assert record.importe_menor == 18_000_000


def test_rechazo_a_record_v1_sin_precio() -> None:
    record = mensaje_rechazada(documento(categoria="jardineria"))
    assert record.tipo == "CotizacionRechazada.v1"
    assert record.causacion == str(ID_COMANDO)
    assert record.motivo == "SIN_OFERTA_PARA_CATEGORIA"
    assert not hasattr(record, "id_proveedor")
    assert not hasattr(record, "importe_menor")


def test_documento_del_tipo_equivocado_falla() -> None:
    with pytest.raises(ValueError):
        mensaje_registrada(documento(categoria="jardineria"))
    with pytest.raises(ValueError):
        mensaje_rechazada(documento())


def test_documento_invalido_falla() -> None:
    with pytest.raises(ValueError):
        mensaje_registrada({"tipo": "CotizacionRegistrada"})
