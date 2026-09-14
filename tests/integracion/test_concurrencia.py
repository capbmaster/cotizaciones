import random
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Lock, local
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from cotizaciones.api.app import create_app
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
from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox, Reserva, SalidaSQL

from ..unitarias.aplicacion.datos import comando_peticion
from ..unitarias.dominio.datos import uuid_lab
from .datos import contar, marcas_sin_efecto, procesar_sql, salidas_enviadas
from .pulsar import LaboratorioPulsar, esperar, peticion_nueva

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


# --- Paso 49: réplicas concurrentes completas (varias instancias FastAPI reales) ---

N_MENSAJES = 200
PORCENTAJE_REPETIDO = 0.10
PORCENTAJE_MISMA_PETICION = 0.05


def _generar_cohorte(n_mensajes: int) -> list[dict[str, Any]]:
    """~10% repite exactamente un mensaje ya enviado; ~5% repite su petición con otro comando."""
    n_repetido = round(n_mensajes * PORCENTAJE_REPETIDO)
    n_misma_peticion = round(n_mensajes * PORCENTAJE_MISMA_PETICION)
    n_originales = n_mensajes - n_repetido - n_misma_peticion
    originales = [peticion_nueva() for _ in range(n_originales)]
    aleatorio = random.Random(1234)
    mensajes = list(originales)
    for _ in range(n_repetido):
        mensajes.append(dict(aleatorio.choice(originales)))  # mismo command_id e id_peticion
    for _ in range(n_misma_peticion):
        base_msg = aleatorio.choice(originales)
        # Mismos datos de negocio (id_trabajo incluido), solo cambia el command_id: es un
        # reenvio idempotente, no un conflicto.
        mensajes.append({**base_msg, "command_id": str(uuid4())})
    aleatorio.shuffle(mensajes)
    return mensajes


@contextmanager
def _contar_confirmaciones_por_propietario() -> Iterator[Counter[str]]:
    """Registra el propietario de cada reserva antes de confirmarla (se limpia luego a NULL)."""
    conteos: Counter[str] = Counter()
    candado = Lock()
    original = RepositorioOutbox.confirmar

    def confirmar(self: RepositorioOutbox, reserva: Reserva) -> bool:
        resultado = original(self, reserva)
        if resultado:
            with candado:
                conteos[reserva.propietario] += 1
        return resultado

    with patch.object(RepositorioOutbox, "confirmar", confirmar):
        yield conteos


@pytest.mark.parametrize("cantidad_instancias", [2, 4])
def test_replicas_concurrentes_completas_bajo_carga_no_duplican(
    base: Database,
    catalogo_v1: CatalogoVigente,
    laboratorio: LaboratorioPulsar,
    cantidad_instancias: int,
) -> None:
    laboratorio.preparar_suscripcion_servicio()
    cohorte = _generar_cohorte(N_MENSAJES)
    ids_unicos = {mensaje["id_peticion"] for mensaje in cohorte}
    for mensaje in cohorte:
        laboratorio.enviar(**mensaje)

    aplicaciones = [create_app(laboratorio.configuracion) for _ in range(cantidad_instancias)]
    with _contar_confirmaciones_por_propietario() as por_propietario:
        with ExitStackDeContextos([TestClient(app) for app in aplicaciones]):
            esperar(lambda: contar(base, CotizacionSQL) == len(ids_unicos), segundos=90)
            esperar(lambda: salidas_enviadas(base) == len(ids_unicos), segundos=90)

    with base.engine.connect() as conexion:
        duplicadas = conexion.execute(
            text(
                "SELECT count(*) FROM (SELECT id_peticion FROM cotizaciones.cotizaciones "
                "GROUP BY id_peticion HAVING count(*) > 1) t"
            )
        ).scalar()
        salidas_por_evento = conexion.execute(
            text(
                "SELECT count(*) FILTER (WHERE enviada_en IS NOT NULL), count(*) "
                "FROM mensajeria.outbox GROUP BY id_evento"
            )
        ).all()

    assert contar(base, CotizacionSQL) == len(ids_unicos)
    assert duplicadas == 0
    assert marcas_sin_efecto(base) == 0
    # Una salida enviada y una sola por evento: ninguna reserva se confirmó dos veces.
    assert all(enviadas == 1 and totales == 1 for enviadas, totales in salidas_por_evento)
    assert sum(por_propietario.values()) == len(ids_unicos)
    print(
        f"[E4/Paso49] {cantidad_instancias} instancias, {len(ids_unicos)} peticiones unicas, "
        f"salidas confirmadas por propietario: {dict(por_propietario)}"
    )


class ExitStackDeContextos:
    """Entra a varios context managers a la vez y los cierra en orden inverso al salir."""

    def __init__(self, contextos: list[Any]) -> None:
        self.contextos = contextos

    def __enter__(self) -> list[Any]:
        return [contexto.__enter__() for contexto in self.contextos]

    def __exit__(self, *excepcion: object) -> None:
        for contexto in reversed(self.contextos):
            contexto.__exit__(*excepcion)
