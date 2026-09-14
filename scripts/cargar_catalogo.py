import argparse
import json
import sys
from pathlib import Path

from cotizaciones.config.database import create_database
from cotizaciones.config.persistencia import crear_uow_cotizaciones
from cotizaciones.config.settings import Settings
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoInvalido
from cotizaciones.modulos.cotizaciones.infraestructura.serializacion import (
    catalogo_desde_documento,
    huella_catalogo,
)

ARCHIVO_V1 = Path(__file__).resolve().parents[1] / "datos" / "catalogos" / "catalogo-v1.json"
CONFLICTO_DE_VERSION = 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Registra una version del catalogo sintetico y, con --activar, la activa."
    )
    parser.add_argument("--archivo", type=Path, default=ARCHIVO_V1)
    parser.add_argument("--activar", action="store_true")
    argumentos = parser.parse_args()
    configuracion = Settings.from_environment()
    if configuracion.database_url is None:
        parser.error("COTIZACIONES_DATABASE_URL es obligatoria")
    try:
        documento = json.loads(argumentos.archivo.read_text(encoding="utf-8"))
        catalogo = catalogo_desde_documento(documento)
    except (OSError, json.JSONDecodeError, CatalogoInvalido) as error:
        print(f"ERROR: archivo de catalogo invalido: {error}", file=sys.stderr)
        return 1
    huella = huella_catalogo(catalogo)
    base = create_database(
        configuracion.database_url,
        pool_size=1,
        max_overflow=0,
        statement_timeout_ms=configuracion.statement_timeout_ms,
    )
    try:
        with crear_uow_cotizaciones(base) as unidad:
            try:
                nueva = unidad.catalogos.registrar_version(catalogo, huella)
            except CatalogoInvalido as error:
                print(f"ERROR: {error}", file=sys.stderr)
                return CONFLICTO_DE_VERSION
            if argumentos.activar:
                unidad.catalogos.activar(catalogo.version)
            vigente = unidad.catalogos.obtener_vigente()
            unidad.confirmar()
    finally:
        base.close()
    estado = "nueva" if nueva else "ya existia con la misma huella"
    print(
        f"Catalogo version {catalogo.version}: {len(catalogo.ofertas)} ofertas, {estado} "
        f"(huella {huella[:12]})"
    )
    print(f"Version activa: {vigente.version if vigente is not None else 'ninguna'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
