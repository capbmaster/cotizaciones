from pulsar.schema import Integer, Record, String


class SolicitarCotizacionV1(Record):
    _avro_namespace = "orquestacion.eventos"

    command_id = String(required=True)
    tipo = String(default="SolicitarCotizacion.v1", required=True, required_default=True)
    version_contrato = Integer(default=1, required=True, required_default=True)
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
