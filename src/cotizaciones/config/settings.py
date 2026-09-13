import os
from dataclasses import dataclass

_PREFIJO_PERSISTENTE = "persistent://"


def _entero(nombre: str, predeterminado: int) -> int:
    valor = os.environ.get(nombre)
    if valor is None:
        return predeterminado
    try:
        return int(valor)
    except ValueError:
        raise ValueError(f"{nombre} debe ser un entero: {valor!r}") from None


@dataclass(frozen=True)
class Settings:
    service_name: str = "cotizaciones"
    database_url: str | None = None
    pool_size: int = 5
    max_overflow: int = 5
    statement_timeout_ms: int = 3000
    pulsar_url: str = "pulsar://127.0.0.1:6650"
    topico_peticiones: str = "persistent://public/default/solicitar-cotizacion-v1"
    suscripcion_peticiones: str = "cotizaciones-peticiones-v1"
    topico_registrada: str = "persistent://public/default/cotizacion-registrada-v1"
    topico_rechazada: str = "persistent://public/default/cotizacion-rechazada-v1"
    pulsar_timeout_segundos: int = 3
    receptor_cola: int = 1
    demora_nack_ms: int = 5000
    retardo_laboratorio_ms: int = 0

    def __post_init__(self) -> None:
        topicos = (self.topico_peticiones, self.topico_registrada, self.topico_rechazada)
        if any(not topico.startswith(_PREFIJO_PERSISTENTE) for topico in topicos):
            raise ValueError("Los topicos deben usar el prefijo persistent://")
        if len(set(topicos)) != len(topicos):
            raise ValueError(
                "Los topicos de peticiones, registrada y rechazada deben ser distintos"
            )
        if not self.suscripcion_peticiones.strip():
            raise ValueError("La suscripcion de peticiones no puede estar vacia")
        positivos = {
            "pool_size": self.pool_size,
            "statement_timeout_ms": self.statement_timeout_ms,
            "pulsar_timeout_segundos": self.pulsar_timeout_segundos,
            "receptor_cola": self.receptor_cola,
            "demora_nack_ms": self.demora_nack_ms,
        }
        for campo, valor in positivos.items():
            if valor <= 0:
                raise ValueError(f"{campo} debe ser positivo")
        if self.max_overflow < 0:
            raise ValueError("max_overflow no puede ser negativo")
        if self.retardo_laboratorio_ms < 0:
            raise ValueError("retardo_laboratorio_ms no puede ser negativo")

    @classmethod
    def from_environment(cls) -> "Settings":
        predeterminado = cls()
        return cls(
            service_name=os.environ.get("COTIZACIONES_SERVICE_NAME", predeterminado.service_name),
            database_url=os.environ.get("COTIZACIONES_DATABASE_URL", "").strip() or None,
            pool_size=_entero("COTIZACIONES_DB_POOL_SIZE", predeterminado.pool_size),
            max_overflow=_entero("COTIZACIONES_DB_MAX_OVERFLOW", predeterminado.max_overflow),
            statement_timeout_ms=_entero(
                "COTIZACIONES_DB_STATEMENT_TIMEOUT_MS", predeterminado.statement_timeout_ms
            ),
            pulsar_url=os.environ.get("COTIZACIONES_PULSAR_URL", predeterminado.pulsar_url),
            topico_peticiones=os.environ.get(
                "COTIZACIONES_TOPICO_PETICIONES", predeterminado.topico_peticiones
            ),
            suscripcion_peticiones=os.environ.get(
                "COTIZACIONES_SUSCRIPCION_PETICIONES", predeterminado.suscripcion_peticiones
            ),
            topico_registrada=os.environ.get(
                "COTIZACIONES_TOPICO_REGISTRADA", predeterminado.topico_registrada
            ),
            topico_rechazada=os.environ.get(
                "COTIZACIONES_TOPICO_RECHAZADA", predeterminado.topico_rechazada
            ),
            pulsar_timeout_segundos=_entero(
                "COTIZACIONES_PULSAR_TIMEOUT_SEGUNDOS", predeterminado.pulsar_timeout_segundos
            ),
            receptor_cola=_entero(
                "COTIZACIONES_PULSAR_RECEPTOR_COLA", predeterminado.receptor_cola
            ),
            demora_nack_ms=_entero(
                "COTIZACIONES_PULSAR_DEMORA_NACK_MS", predeterminado.demora_nack_ms
            ),
            retardo_laboratorio_ms=_entero(
                "COTIZACIONES_RETARDO_LABORATORIO_MS", predeterminado.retardo_laboratorio_ms
            ),
        )
