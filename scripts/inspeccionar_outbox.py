import json

from cotizaciones.config.database import create_database
from cotizaciones.config.settings import Settings
from cotizaciones.seedwork.infraestructura.outbox import RepositorioOutbox


def main() -> None:
    configuracion = Settings.from_environment()
    if configuracion.database_url is None:
        raise SystemExit("COTIZACIONES_DATABASE_URL es obligatoria")
    base = create_database(
        configuracion.database_url,
        pool_size=1,
        max_overflow=0,
        statement_timeout_ms=configuracion.statement_timeout_ms,
    )
    try:
        outbox = RepositorioOutbox(base.session_factory)
        print(
            json.dumps(
                dict(metricas=outbox.metricas(), pendientes=outbox.inspeccionar()),
                default=str,
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        base.close()


if __name__ == "__main__":
    main()
