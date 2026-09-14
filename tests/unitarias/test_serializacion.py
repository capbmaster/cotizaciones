import json
from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from cotizaciones.modulos.cotizaciones.dominio.eventos import (
    CotizacionRechazada,
    CotizacionRegistrada,
)
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoInvalido
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    Dinero,
    TipoRed,
)
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import (
    catalogo_desde_documento,
    decodificar_comando,
    decodificar_evento,
    decodificar_peticion,
    huella_catalogo,
    serializar_comando,
    serializar_evento,
    serializar_peticion,
)
from cotizaciones.seedwork.dominio.eventos import EventoDominio

from .aplicacion.datos import comando_peticion
from .dominio.datos import (
    A101,
    ID_COMANDO,
    ID_COTIZACION,
    ID_EVENTO,
    ID_PETICION,
    ID_POLITICA,
    ID_SOLICITUD,
    ID_TRABAJO,
    INSTANTE_RESULTADO,
    PARTNER_LAB,
    catalogo_laboratorio,
    cotizacion_resuelta,
    datos_peticion,
)

ARCHIVO_V1 = Path(__file__).resolve().parents[2] / "datos" / "catalogos" / "catalogo-v1.json"


def propuesta() -> CotizacionRegistrada:
    (evento,) = cotizacion_resuelta().retirar_eventos()
    assert isinstance(evento, CotizacionRegistrada)
    return evento


def rechazo() -> CotizacionRechazada:
    (evento,) = cotizacion_resuelta(categoria="jardineria").retirar_eventos()
    assert isinstance(evento, CotizacionRechazada)
    return evento


def documento_v1() -> dict[str, Any]:
    documento: dict[str, Any] = json.loads(ARCHIVO_V1.read_text(encoding="utf-8"))
    return documento


@pytest.mark.parametrize("fabrica", [propuesta, rechazo], ids=["propuesta", "rechazo"])
def test_ida_y_vuelta_exacta_de_ambos_eventos(fabrica: Any) -> None:
    original = fabrica()
    documento = serializar_evento(original)
    assert decodificar_evento(documento) == original
    assert json.loads(json.dumps(documento)) == documento


def test_documento_de_la_propuesta() -> None:
    assert serializar_evento(propuesta()) == {
        "tipo": "CotizacionRegistrada",
        "version_formato": 2,
        "id_evento": str(ID_EVENTO),
        "instante": "2026-09-12T15:00:04+00:00",
        "id_cotizacion": str(ID_COTIZACION),
        "peticion": serializar_peticion(datos_peticion()),
        "id_comando": str(ID_COMANDO),
        "correlacion": str(ID_SOLICITUD),
        "version_catalogo": 1,
        "version_cotizacion": 1,
        "id_proveedor": str(A101),
        "importe_menor": 15_000_000,
        "moneda": "COP",
        "duracion_estimada_minutos": None,
    }


def test_documento_del_rechazo_lleva_motivo_y_ningun_precio() -> None:
    documento = serializar_evento(rechazo())
    assert documento["tipo"] == "CotizacionRechazada"
    assert documento["motivo"] == "SIN_OFERTA_PARA_CATEGORIA"
    assert not {"id_proveedor", "importe_menor", "moneda"} & documento.keys()


def test_el_importe_conserva_su_valor_entero_exacto() -> None:
    grande = 2**53 + 1  # un float no lo representa exactamente
    original = replace(propuesta(), precio=Dinero(importe_menor=grande, moneda="COP"))
    documento = json.loads(json.dumps(serializar_evento(original)))
    assert type(documento["importe_menor"]) is int
    assert documento["importe_menor"] == grande
    decodificado = decodificar_evento(documento)
    assert isinstance(decodificado, CotizacionRegistrada)
    assert decodificado.precio.importe_menor == grande


def test_el_instante_se_escribe_en_utc() -> None:
    bogota = timezone(timedelta(hours=-5))
    original = replace(propuesta(), instante=INSTANTE_RESULTADO.astimezone(bogota))
    documento = serializar_evento(original)
    assert documento["instante"] == "2026-09-12T15:00:04+00:00"
    assert decodificar_evento(documento) == original


@pytest.mark.parametrize(
    "cambio",
    [
        pytest.param({"version_formato": 3}, id="formato-3-desconocido"),
        pytest.param({"version_formato": "1"}, id="formato-no-entero"),
        pytest.param({"tipo": "CotizacionDesconocida"}, id="tipo-desconocido"),
    ],
)
def test_formato_o_tipo_desconocido_falla(cambio: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        decodificar_evento({**serializar_evento(propuesta()), **cambio})


def test_documento_incompleto_falla_con_value_error() -> None:
    documento = serializar_evento(propuesta())
    del documento["id_proveedor"]
    with pytest.raises(ValueError):
        decodificar_evento(documento)


def test_serializar_valida_decodificando_de_vuelta() -> None:
    corrupto = propuesta()
    object.__setattr__(corrupto, "version_catalogo", 0)
    with pytest.raises(ValueError):
        serializar_evento(corrupto)


def test_serializar_rechaza_eventos_de_otro_tipo() -> None:
    with pytest.raises(ValueError):
        serializar_evento(EventoDominio(id_evento=ID_EVENTO, instante=INSTANTE_RESULTADO))


@pytest.mark.parametrize("duracion", [30, 90, None])
def test_ida_y_vuelta_de_la_duracion_estimada(duracion: int | None) -> None:
    original = replace(propuesta(), duracion_estimada_minutos=duracion)
    documento = serializar_evento(original)
    assert documento["version_formato"] == 2
    assert documento["duracion_estimada_minutos"] == duracion
    assert decodificar_evento(documento) == original


def test_un_documento_formato_1_historico_decodifica_duracion_nula() -> None:
    """Filas v1 (sin la clave, escritas antes del Paso 54) se leen con duracion desconocida."""
    documento = serializar_evento(propuesta())
    documento["version_formato"] = 1
    del documento["duracion_estimada_minutos"]
    decodificado = decodificar_evento(documento)
    assert isinstance(decodificado, CotizacionRegistrada)
    assert decodificado.duracion_estimada_minutos is None


def test_peticion_con_uuid_en_texto_y_enumeraciones_por_valor() -> None:
    datos = datos_peticion(categoria="  Plomeria ", tipo_red=TipoRed.HOMOLOGADA_PARTNER)
    documento = serializar_peticion(datos)
    assert documento == {
        "id_peticion": str(ID_PETICION),
        "id_trabajo": str(ID_TRABAJO),
        "id_solicitud": str(ID_SOLICITUD),
        "id_partner": str(PARTNER_LAB),
        "categoria": "  Plomeria ",
        "tipo_solicitud": "SINIESTRO",
        "tipo_red": "HOMOLOGADA_PARTNER",
        "id_politica": str(ID_POLITICA),
        "version_politica": 1,
    }
    assert decodificar_peticion(documento) == datos


def test_comando_ida_y_vuelta_y_documentos_identicos() -> None:
    documento = serializar_comando(comando_peticion())
    assert documento == serializar_comando(comando_peticion())
    assert set(documento) == {"command_id", "instante", "correlacion", "causacion", "datos"}
    assert documento["command_id"] == str(ID_COMANDO)
    assert documento["instante"] == "2026-09-12T15:00:03+00:00"
    assert decodificar_comando(documento) == comando_peticion()


def test_comandos_con_otros_datos_producen_otro_documento() -> None:
    assert serializar_comando(comando_peticion()) != serializar_comando(
        comando_peticion(categoria="electricidad")
    )


def test_el_archivo_v1_contiene_las_cinco_ofertas_del_laboratorio_sin_duracion() -> None:
    documento = documento_v1()
    assert all("duracion_estimada_minutos" not in o for o in documento["ofertas"])
    catalogo = catalogo_desde_documento(documento)
    assert catalogo.version == 1
    assert set(catalogo.ofertas) == set(catalogo_laboratorio().ofertas)


def test_la_carga_normaliza_la_categoria() -> None:
    documento = documento_v1()
    documento["ofertas"] = [{**documento["ofertas"][0], "categoria": "  Plomeria "}]
    assert catalogo_desde_documento(documento).ofertas[0].categoria == "plomeria"


@pytest.mark.parametrize(
    "cambio",
    [
        {"importe_menor": 0},
        {"importe_menor": 1.5},
        {"tipo_red": "OTRA_RED"},
        {"id_partner": str(PARTNER_LAB)},
        {"moneda": "cop"},
        {"id_proveedor": "no-es-uuid"},
    ],
)
def test_oferta_invalida_en_el_archivo_es_catalogo_invalido(cambio: dict[str, Any]) -> None:
    documento = documento_v1()
    documento["ofertas"][0] = {**documento["ofertas"][0], **cambio}
    with pytest.raises(CatalogoInvalido):
        catalogo_desde_documento(documento)


@pytest.mark.parametrize(
    "documento",
    [
        {"ofertas": []},
        {"version": 1},
        {"version": 1, "ofertas": []},
        {"version": "1", "ofertas": [{"id_proveedor": str(A101)}]},
        {"version": 1, "ofertas": [{"categoria": "plomeria"}]},
    ],
)
def test_documento_de_catalogo_incompleto_es_catalogo_invalido(
    documento: dict[str, Any],
) -> None:
    with pytest.raises(CatalogoInvalido):
        catalogo_desde_documento(documento)


def test_la_huella_no_depende_del_orden_ni_de_la_forma_de_la_categoria() -> None:
    catalogo = catalogo_desde_documento(documento_v1())
    invertido = CatalogoVigente(version=1, ofertas=tuple(reversed(catalogo.ofertas)))
    mayusculas = documento_v1()
    for oferta in mayusculas["ofertas"]:
        oferta["categoria"] = f"  {oferta['categoria'].upper()} "
    huella = huella_catalogo(catalogo)
    assert len(huella) == 64 and int(huella, 16) >= 0
    assert huella_catalogo(invertido) == huella
    assert huella_catalogo(catalogo_desde_documento(mayusculas)) == huella


def test_la_huella_cambia_si_cambia_el_contenido_o_la_version() -> None:
    catalogo = catalogo_desde_documento(documento_v1())
    otro_importe = documento_v1()
    otro_importe["ofertas"][0]["importe_menor"] = 15_000_001
    assert huella_catalogo(catalogo_desde_documento(otro_importe)) != huella_catalogo(catalogo)
    assert huella_catalogo(replace(catalogo, version=2)) != huella_catalogo(catalogo)
