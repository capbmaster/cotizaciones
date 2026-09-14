import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

# Cada fase añade aquí los imports clave que cree.
VERIFICACION = """
import sys
from pathlib import Path

import cotizaciones
from cotizaciones.api.app import create_app
from cotizaciones.config.database import create_database
from cotizaciones.config.settings import Settings
from cotizaciones.infraestructura.ciclo_vida import EstadoMensajeria, procesar_mensajeria
from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.servicios import resolver_oferta
from cotizaciones.seedwork.aplicacion.excepciones import ColisionPersistencia
from cotizaciones.seedwork.dominio.entidades import AgregacionRaiz

fuente = Path(sys.argv[1]).resolve()
paquete = Path(cotizaciones.__file__).resolve()
assert paquete.is_relative_to(Path(sys.prefix).resolve()), paquete
assert not paquete.is_relative_to(fuente), paquete
assert create_app(Settings()).title == "Cotizaciones"
assert callable(create_database) and callable(procesar_mensajeria)
assert EstadoMensajeria().listo()
assert issubclass(ColisionPersistencia, RuntimeError)
assert issubclass(Cotizacion, AgregacionRaiz)
assert callable(resolver_oferta)
print(f"Wheel instalado importado fuera del arbol fuente: {paquete}")
"""


def main() -> None:
    proyecto = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="cotizaciones-distribution-") as directorio_temporal:
        temporal = Path(directorio_temporal)
        ruta_entorno = temporal / "environment"
        entorno = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(ruta_entorno)}
        subprocess.run(
            ["uv", "sync", "--locked", "--no-editable", "--no-dev"],
            cwd=proyecto,
            env=entorno,
            check=True,
        )
        subprocess.run(
            ["uv", "build", "--out-dir", str(temporal / "dist")],
            cwd=proyecto,
            check=True,
        )
        wheel = next((temporal / "dist").glob("*.whl"))
        interprete = ruta_entorno / "bin" / "python"
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(interprete),
                "--no-deps",
                "--reinstall",
                str(wheel),
            ],
            check=True,
        )
        subprocess.run(
            [str(interprete), "-I", "-c", VERIFICACION, str(proyecto / "src")],
            cwd=temporal,
            check=True,
        )


if __name__ == "__main__":
    main()
