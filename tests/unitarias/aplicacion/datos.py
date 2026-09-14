from typing import Any

from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion

from ..dominio.datos import datos_peticion, origen_comando


def comando_peticion(
    *, origen: dict[str, Any] | None = None, **cambios_peticion: Any
) -> ProcesarPeticionCotizacion:
    """Comando propio de la F1 (IDs de 00 §10); `origen` y `cambios_peticion` sustituyen campos."""
    return ProcesarPeticionCotizacion(
        origen=origen_comando(**(origen or {})), datos=datos_peticion(**cambios_peticion)
    )
