from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from cotizaciones.config.bootstrap import componer_consulta, componer_listado
from cotizaciones.config.database import Database
from cotizaciones.modulos.cotizaciones.aplicacion.consultas import (
    FiltroCotizaciones,
    VistaCotizacion,
)
from cotizaciones.modulos.cotizaciones.aplicacion.handlers.consultar_cotizaciones import (
    ConsultarCotizacionHandler,
    ListarCotizacionesHandler,
)
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import EstadoCotizacion

router = APIRouter(prefix="/cotizaciones", tags=["cotizaciones"])


def obtener_base(request: Request) -> Database:
    base = cast(Database | None, request.app.state.database)
    if base is None:
        raise HTTPException(503, "Base de datos no configurada")
    return base


def obtener_consulta(
    base: Annotated[Database, Depends(obtener_base)],
) -> ConsultarCotizacionHandler:
    return componer_consulta(base)


def obtener_listado(base: Annotated[Database, Depends(obtener_base)]) -> ListarCotizacionesHandler:
    return componer_listado(base)


@router.get(
    "/{id_cotizacion}",
    response_model=VistaCotizacion,
    responses={404: {"description": "No hay una resolucion confirmada con ese ID"}},
)
def consultar_cotizacion(
    id_cotizacion: UUID,
    consultar: Annotated[ConsultarCotizacionHandler, Depends(obtener_consulta)],
) -> VistaCotizacion:
    vista = consultar(id_cotizacion)
    if vista is None:
        raise HTTPException(404, "cotizacion no encontrada")
    return vista


@router.get("", response_model=list[VistaCotizacion])
def listar_cotizaciones(
    listar: Annotated[ListarCotizacionesHandler, Depends(obtener_listado)],
    id_peticion: UUID | None = None,
    id_trabajo: UUID | None = None,
    estado: EstadoCotizacion | None = None,
    limite: Annotated[int, Query(ge=1, le=100)] = 20,
    desplazamiento: Annotated[int, Query(ge=0)] = 0,
) -> list[VistaCotizacion]:
    filtro = FiltroCotizaciones(id_peticion=id_peticion, id_trabajo=id_trabajo, estado=estado)
    return listar(filtro, limite, desplazamiento)
