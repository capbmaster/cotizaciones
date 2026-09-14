import os

from alembic import context
from sqlalchemy import Connection

from cotizaciones.config.database import create_database
from cotizaciones.config.persistencia import metadata

# Una migración puede esperar bloqueos: margen mayor que el statement_timeout del servicio.
TIMEOUT_MIGRACION_MS = 60_000


def ejecutar(conexion: Connection) -> None:
    context.configure(connection=conexion, target_metadata=metadata, include_schemas=True)
    with context.begin_transaction():
        context.run_migrations()


conexion = context.config.attributes.get("connection")
if conexion is not None:
    ejecutar(conexion)
else:
    base = create_database(
        os.environ["COTIZACIONES_DATABASE_URL"],
        pool_size=1,
        max_overflow=0,
        statement_timeout_ms=TIMEOUT_MIGRACION_MS,
    )
    try:
        with base.engine.connect() as conexion:
            ejecutar(conexion)
    finally:
        base.close()
