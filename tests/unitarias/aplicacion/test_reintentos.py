import pytest

from cotizaciones.seedwork.aplicacion.excepciones import ColisionPersistencia
from cotizaciones.seedwork.aplicacion.reintentos import reintentar_colision


@pytest.mark.parametrize(
    ("tipo_error", "intentos_esperados"), [(ColisionPersistencia, 3), (ValueError, 1)]
)
def test_reintento_acotado_y_solo_ante_colisiones(
    tipo_error: type[Exception], intentos_esperados: int
) -> None:
    intentos = 0

    @reintentar_colision
    def fallar() -> None:
        nonlocal intentos
        intentos += 1
        raise tipo_error("Fallo")

    with pytest.raises(tipo_error):
        fallar()
    assert intentos == intentos_esperados


def test_colision_transitoria_se_supera_en_el_siguiente_intento() -> None:
    intentos = 0

    @reintentar_colision
    def operar() -> str:
        nonlocal intentos
        intentos += 1
        if intentos == 1:
            raise ColisionPersistencia("carrera")
        return "ok"

    assert operar() == "ok"
    assert intentos == 2
