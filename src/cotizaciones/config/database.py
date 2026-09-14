from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    def close(self) -> None:
        self.engine.dispose()

    def verificar(self) -> bool:
        try:
            with self.engine.connect() as conexion:
                conexion.execute(text("SELECT 1"))
        except Exception:
            return False
        return True


def create_database(
    database_url: str, *, pool_size: int, max_overflow: int, statement_timeout_ms: int
) -> Database:
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("La URL de base de datos debe usar postgresql+psycopg")
    engine = create_engine(
        url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        # search_path fijo: con el search_path por defecto ("$user", public) el esquema
        # "cotizaciones" coincide con el usuario "cotizaciones" y pasaría a ser el esquema
        # por defecto, confundiendo la reflexión de Alembic y la ubicación de alembic_version.
        connect_args={
            "options": f"-c statement_timeout={statement_timeout_ms} -c search_path=public"
        },
    )
    return Database(engine=engine, session_factory=sessionmaker(bind=engine))
