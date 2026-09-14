from collections.abc import Callable
from functools import wraps

from cotizaciones.seedwork.aplicacion.excepciones import ColisionPersistencia


def reintentar_colision[**Parametros, Resultado](
    operacion: Callable[Parametros, Resultado],
) -> Callable[Parametros, Resultado]:
    @wraps(operacion)
    def ejecutar(*argumentos: Parametros.args, **opciones: Parametros.kwargs) -> Resultado:
        for intento in range(3):
            try:
                return operacion(*argumentos, **opciones)
            except ColisionPersistencia:
                if intento == 2:
                    raise
        raise AssertionError("Reintentos agotados")

    return ejecutar
