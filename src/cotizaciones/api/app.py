from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated, cast

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from cotizaciones.api.cotizaciones import router as router_cotizaciones
from cotizaciones.config.database import Database, create_database
from cotizaciones.config.settings import Settings
from cotizaciones.infraestructura.ciclo_vida import EstadoMensajeria, procesar_mensajeria
from cotizaciones.seedwork.aplicacion.excepciones import ColisionPersistencia


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def crear_base(configuracion: Settings) -> Database:
    if configuracion.database_url is None:
        raise ValueError("No hay URL de base de datos configurada")
    return create_database(
        configuracion.database_url,
        pool_size=configuracion.pool_size,
        max_overflow=configuracion.max_overflow,
        statement_timeout_ms=configuracion.statement_timeout_ms,
    )


def _no_listo(motivo: str, componentes: dict[str, dict[str, str | None]]) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"status": "no_listo", "motivo": motivo, "componentes": componentes},
    )


def create_app(
    settings: Settings | None = None,
    database_factory: Callable[[Settings], Database] = crear_base,
    processing_factory: Callable[
        [Database, Settings], AbstractAsyncContextManager[EstadoMensajeria]
    ] = procesar_mensajeria,
) -> FastAPI:
    configuracion = settings if settings is not None else Settings.from_environment()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database = database_factory(configuracion) if configuracion.database_url else None
        application.state.database = database
        try:
            if database is None:
                yield
            else:
                async with processing_factory(database, configuracion) as estado:
                    application.state.estado_mensajeria = estado
                    yield
        finally:
            application.state.estado_mensajeria = None
            application.state.database = None
            if database is not None:
                database.close()

    application = FastAPI(title="Cotizaciones", lifespan=lifespan)
    application.include_router(router_cotizaciones)

    async def fallo_persistencia(request: Request, error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=503, content={"detail": "Persistencia temporalmente no disponible"}
        )

    application.add_exception_handler(SQLAlchemyError, fallo_persistencia)
    application.add_exception_handler(ColisionPersistencia, fallo_persistencia)
    application.state.settings = configuracion
    application.state.database = None
    application.state.estado_mensajeria = None

    @application.get("/health/live", tags=["health"])
    def liveness(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
        return {"status": "ok", "service": settings.service_name}

    @application.get("/health/ready", tags=["health"])
    def readiness(request: Request) -> JSONResponse:
        # Endpoint síncrono: FastAPI lo ejecuta en su pool de hilos, fuera del event loop.
        database: Database | None = request.app.state.database
        estado: EstadoMensajeria | None = request.app.state.estado_mensajeria
        componentes = estado.resumen() if estado is not None else {}
        if database is None:
            return _no_listo("base_no_configurada", componentes)
        if not database.verificar():
            return _no_listo("base_no_disponible", componentes)
        if estado is None or not estado.listo():
            return _no_listo("mensajeria_no_operativa", componentes)
        return JSONResponse(content={"status": "listo", "componentes": componentes})

    return application
