from pulsar.schema import Integer, Long, Record, String

# Revision 2 de CotizacionRegistrada.v1 (Paso 55, E3): mismo record, mismo topico, mismo tipo.
# Campos 1-18 identicos a esquemas/v1/eventos.py::CotizacionRegistradaV1; el campo 19 es aditivo,
# union null/int con default null (confirmado en la evidencia 01: el SDK 3.13.0 emite el default
# con required_default=True y decodifica la ausencia como None).
# CotizacionRechazadaV1 no tiene revision 2: el rechazo no cambia (ver docs/plans/08).


class CotizacionRegistradaV1(Record):
    event_id = String(required=True)
    tipo = String(required=True)
    version_contrato = Integer(required=True)
    instante = String(required=True)
    correlacion = String(required=True)
    causacion = String(required=True)
    id_peticion = String(required=True)
    id_trabajo = String(required=True)
    id_solicitud = String(required=True)
    id_partner = String(required=True)
    version_catalogo = Integer(required=True)
    version_cotizacion = Integer(required=True)
    id_cotizacion = String(required=True)
    id_proveedor = String(required=True)
    importe_menor = Long(required=True)
    moneda = String(required=True)
    categoria = String(required=True)
    tipo_red = String(required=True)
    duracion_estimada_minutos = Integer(default=None, required_default=True)
