from typing import Any

from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion

from ..dominio.datos import (
    CAUSACION,
    ID_COMANDO,
    ID_PETICION,
    ID_POLITICA,
    ID_SOLICITUD,
    ID_TRABAJO,
    PARTNER_LAB,
    datos_peticion,
    origen_comando,
)

# Valores del mensaje SolicitarCotizacion.v1 de la F1 (igual al ejemplo público de 00 §10).
MENSAJE_COMANDO_F1: dict[str, Any] = {
    "command_id": str(ID_COMANDO),
    "tipo": "SolicitarCotizacion.v1",
    "version_contrato": 1,
    "instante": "2026-09-12T15:00:03+00:00",
    "correlacion": str(ID_SOLICITUD),
    "causacion": str(CAUSACION),
    "id_peticion": str(ID_PETICION),
    "id_trabajo": str(ID_TRABAJO),
    "id_solicitud": str(ID_SOLICITUD),
    "id_partner": str(PARTNER_LAB),
    "categoria": "plomeria",
    "tipo_solicitud": "SINIESTRO",
    "tipo_red": "GENERAL_HDA",
    "id_politica": str(ID_POLITICA),
    "version_politica": 1,
}


def comando_peticion(
    *, origen: dict[str, Any] | None = None, **cambios_peticion: Any
) -> ProcesarPeticionCotizacion:
    """Comando propio de la F1 (IDs de 00 §10); `origen` y `cambios_peticion` sustituyen campos."""
    return ProcesarPeticionCotizacion(
        origen=origen_comando(**(origen or {})), datos=datos_peticion(**cambios_peticion)
    )
