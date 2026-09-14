from pulsar.schema import Integer, Long, Record, String

# Congelado desde el Paso 53: la revisión 2 vive en esquemas/v2/eventos.py.


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


class CotizacionRechazadaV1(Record):
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
    motivo = String(required=True)
