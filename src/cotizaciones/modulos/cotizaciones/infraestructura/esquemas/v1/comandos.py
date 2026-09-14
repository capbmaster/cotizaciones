from pulsar.schema import Integer, Record, String


class SolicitarCotizacionV1(Record):
    """Lector provisional de SolicitarCotizacion.v1 (propietario: Orquestación; ver 00 §3)."""

    command_id = String(required=True)
    tipo = String(required=True)
    version_contrato = Integer(required=True)
    instante = String(required=True)
    correlacion = String(required=True)
    causacion = String(required=True)
    id_peticion = String(required=True)
    id_trabajo = String(required=True)
    id_solicitud = String(required=True)
    id_partner = String(required=True)
    categoria = String(required=True)
    tipo_solicitud = String(required=True)
    tipo_red = String(required=True)
    id_politica = String(required=True)
    version_politica = Integer(required=True)
