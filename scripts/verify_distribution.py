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
from cotizaciones.config.bootstrap import componer_procesamiento, componer_procesamiento_sql
from cotizaciones.config.database import create_database
from cotizaciones.config.persistencia import crear_uow_cotizaciones, metadata
from cotizaciones.seedwork.infraestructura.despacho_outbox import DespachadorOutbox
from pulsar.schema import AvroSchema
from cotizaciones.infraestructura.despacho import iniciar_despacho
from cotizaciones.modulos.cotizaciones.infraestructura.consumidor_peticiones import (
    ConsumidorPeticiones,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.comandos import (
    SolicitarCotizacionV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.esquemas.v1.eventos import (
    CotizacionRechazadaV1,
    CotizacionRegistradaV1,
)
from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores_eventos import (
    comando_desde_mensaje,
    mensaje_rechazada,
    mensaje_registrada,
)
from cotizaciones.seedwork.infraestructura.ciclos import iniciar_ciclo
from cotizaciones.seedwork.infraestructura.publicador_pulsar import PublicadorPulsar
from cotizaciones.config.settings import Settings
from cotizaciones.infraestructura.ciclo_vida import EstadoMensajeria, procesar_mensajeria
from cotizaciones.modulos.cotizaciones.aplicacion.handlers.procesar_peticion import (
    ProcesarPeticionHandler,
)
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
assert callable(componer_procesamiento)
assert ProcesarPeticionHandler.consumidor == "cotizaciones.procesar_peticion"
assert callable(componer_procesamiento_sql) and callable(crear_uow_cotizaciones)
assert callable(DespachadorOutbox)
for record in (SolicitarCotizacionV1, CotizacionRegistradaV1, CotizacionRechazadaV1):
    assert AvroSchema(record) is not None and "namespace" not in record.schema()
assert callable(comando_desde_mensaje) and callable(mensaje_registrada)
assert callable(mensaje_rechazada) and callable(ConsumidorPeticiones)
assert callable(PublicadorPulsar) and callable(iniciar_ciclo) and callable(iniciar_despacho)
assert {
    "cotizaciones.catalogos",
    "cotizaciones.ofertas_catalogo",
    "cotizaciones.cotizaciones",
    "mensajeria.inbox",
    "mensajeria.outbox",
    "mensajeria.eventos",
} <= set(metadata.tables)
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
