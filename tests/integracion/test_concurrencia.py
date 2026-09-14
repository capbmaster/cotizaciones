from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, local
from typing import Any
from unittest.mock import patch

from cotizaciones.config.database import Database
from cotizaciones.modulos.cotizaciones.aplicacion.comandos import ProcesarPeticionCotizacion
from cotizaciones.modulos.cotizaciones.aplicacion.excepciones import ConflictoPeticion
from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ResultadoProcesamiento,
)
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import CatalogoVigente
from cotizaciones.modulos.cotizaciones.infraestructura.orm import CotizacionSQL
from cotizaciones.modulos.cotizaciones.infraestructura.repositorios import (
    RepositorioCotizacionesSQL,
)
from cotizaciones.seedwork.infraestructura.inbox import EntradaSQL
from cotizaciones.seedwork.infraestructura.outbox import SalidaSQL

from ..unitarias.aplicacion.datos import comando_peticion
from ..unitarias.dominio.datos import uuid_lab
from .datos import contar, marcas_sin_efecto, procesar_sql

OTRO_COMANDO = uuid_lab("0023")


@contextmanager
def sincronizar_lecturas(clase: type, metodo: str) -> Iterator[None]:
    """Cada hilo espera en una barrera tras su primera lectura: ambos leen antes de escribir."""
    barrera = Barrier(2)
    estado = local()
    original: Callable[..., Any] = getattr(clase, metodo)

    def leer(*argumentos: Any, **opciones: Any) -> Any:
        valor = original(*argumentos, **opciones)
        if not getattr(estado, "esperado", False):
            estado.esperado = True
            barrera.wait(timeout=5)
        return valor

    with patch.object(clase, metodo, leer):
        yield


def en_dos_replicas(
    base: Database, comandos: list[ProcesarPeticionCotizacion]
) -> list[ResultadoProcesamiento | Exception]:
    procesar = procesar_sql(base)
    resultados: list[ResultadoProcesamiento | Exception] = []
    with sincronizar_lecturas(RepositorioCotizacionesSQL, "obtener_por_peticion"):
        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            futuros = [ejecutor.submit(procesar, comando) for comando in comandos]
            for futuro in futuros:
                try:
                    resultados.append(futuro.result(timeout=20))
                except Exception as error:
                    resultados.append(error)
    return resultados


def conteos(base: Database) -> tuple[int, int, int]:
    return contar(base, CotizacionSQL), contar(base, EntradaSQL), contar(base, SalidaSQL)


def test_mismo_command_id_en_dos_replicas(base: Database, catalogo_v1: CatalogoVigente) -> None:
    resultados = en_dos_replicas(base, [comando_peticion(), comando_peticion()])
    assert all(isinstance(r, ResultadoProcesamiento) for r in resultados), resultados
    nuevas = [r for r in resultados if isinstance(r, ResultadoProcesamiento) and r.nueva]
    sin_efecto = [r for r in resultados if isinstance(r, ResultadoProcesamiento) and not r.nueva]
    assert len(nuevas) == 1 and len(sin_efecto) == 1
    # La segunda réplica esperó el commit de la primera sobre la clave del inbox.
    assert sin_efecto[0].id_cotizacion is None
    assert conteos(base) == (1, 1, 1)
    assert marcas_sin_efecto(base) == 0


def test_distinto_command_id_misma_peticion_en_dos_replicas(
    base: Database, catalogo_v1: CatalogoVigente
) -> None:
    comandos = [comando_peticion(), comando_peticion(origen={"id_comando": OTRO_COMANDO})]
    resultados = en_dos_replicas(base, comandos)
    assert all(isinstance(r, ResultadoProcesamiento) for r in resultados), resultados
    ids = {r.id_cotizacion for r in resultados if isinstance(r, ResultadoProcesamiento)}
    nuevas = [r.nueva for r in resultados if isinstance(r, ResultadoProcesamiento)]
    assert len(ids) == 1 and None not in ids
    assert sorted(nuevas) == [False, True]
    assert conteos(base) == (1, 2, 1)
    assert marcas_sin_efecto(base) == 0


def test_datos_contradictorios_en_dos_replicas(
    base: Database, catalogo_v1: CatalogoVigente
) -> None:
    comandos = [
        comando_peticion(),
        comando_peticion(origen={"id_comando": OTRO_COMANDO}, categoria="electricidad"),
    ]
    resultados = en_dos_replicas(base, comandos)
    exitos = [r for r in resultados if isinstance(r, ResultadoProcesamiento)]
    conflictos = [r for r in resultados if isinstance(r, ConflictoPeticion)]
    assert len(exitos) == 1 and len(conflictos) == 1, resultados
    assert exitos[0].nueva is True
    assert conteos(base) == (1, 1, 1)
    assert marcas_sin_efecto(base) == 0
