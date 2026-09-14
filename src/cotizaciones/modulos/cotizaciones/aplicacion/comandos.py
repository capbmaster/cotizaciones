from dataclasses import dataclass

from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import DatosPeticion, OrigenComando


@dataclass(frozen=True, kw_only=True)
class ProcesarPeticionCotizacion:
    """Comando propio que produce el traductor de mensajería; nunca un Record Avro."""

    origen: OrigenComando
    datos: DatosPeticion

    def __post_init__(self) -> None:
        if not isinstance(self.origen, OrigenComando) or not isinstance(self.datos, DatosPeticion):
            raise ValueError("El comando requiere origen y datos de peticion propios")
