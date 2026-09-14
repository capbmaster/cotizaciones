from collections.abc import Callable
from uuid import UUID, uuid5

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from cotizaciones.modulos.cotizaciones.aplicacion.consultas import (
    FiltroCotizaciones,
    VistaCotizacion,
)
from cotizaciones.modulos.cotizaciones.dominio.entidades import Cotizacion
from cotizaciones.modulos.cotizaciones.dominio.excepciones import CatalogoInvalido
from cotizaciones.modulos.cotizaciones.dominio.objetos_valor import (
    CatalogoVigente,
    EstadoCotizacion,
    MotivoRechazo,
    OfertaCatalogo,
    TipoRed,
    TipoSolicitud,
)
from cotizaciones.modulos.cotizaciones.infraestructura.mapeadores import (
    cargar_catalogo,
    cargar_cotizacion,
    valores_cotizacion,
    valores_oferta,
)
from cotizaciones.modulos.cotizaciones.infraestructura.orm import (
    CatalogoSQL,
    CotizacionSQL,
    OfertaCatalogoSQL,
)

ESPACIO_OFERTAS = UUID("0c7b9e4a-5d2f-4b8e-a1c3-7f6e5d4c3b2a")


def id_oferta(version: int, oferta: OfertaCatalogo) -> UUID:
    """UUID v5 determinista de «versión|categoría|red|partner|proveedor»."""
    partner = str(oferta.id_partner) if oferta.id_partner is not None else ""
    return uuid5(
        ESPACIO_OFERTAS,
        f"{version}|{oferta.categoria}|{oferta.tipo_red.value}|{partner}|{oferta.id_proveedor}",
    )


class RepositorioCotizacionesSQL:
    def __init__(self, sesion: Session) -> None:
        self.sesion = sesion

    def obtener_por_peticion(self, id_peticion: UUID) -> Cotizacion | None:
        fila = self.sesion.scalar(
            select(CotizacionSQL).where(CotizacionSQL.id_peticion == id_peticion)
        )
        return cargar_cotizacion(fila) if fila is not None else None

    def guardar(self, cotizacion: Cotizacion) -> None:
        # Una violación de uq_cotizacion_peticion sale del flush; la UoW la convierte en
        # ColisionPersistencia para que el handler reintente.
        self.sesion.add(CotizacionSQL(**valores_cotizacion(cotizacion)))
        self.sesion.flush()


class RepositorioCatalogoSQL:
    def __init__(self, sesion: Session) -> None:
        self.sesion = sesion

    def obtener_vigente(self) -> CatalogoVigente | None:
        catalogo = self.sesion.scalar(select(CatalogoSQL).where(CatalogoSQL.activo.is_(True)))
        if catalogo is None:
            return None
        ofertas = self.sesion.scalars(
            select(OfertaCatalogoSQL)
            .where(OfertaCatalogoSQL.version_catalogo == catalogo.version)
            .order_by(OfertaCatalogoSQL.id_proveedor, OfertaCatalogoSQL.id)
        ).all()
        return cargar_catalogo(catalogo, ofertas)

    def registrar_version(self, catalogo: CatalogoVigente, huella: str) -> bool:
        """Verdadero si la versión es nueva; falso si ya existía con la misma huella."""
        existente = self.sesion.get(CatalogoSQL, catalogo.version)
        if existente is not None:
            if existente.huella != huella:
                raise CatalogoInvalido(
                    f"La version {catalogo.version} del catalogo ya existe con otro contenido"
                )
            return False
        self.sesion.add(CatalogoSQL(version=catalogo.version, huella=huella, activo=False))
        self.sesion.flush()
        self.sesion.add_all(
            OfertaCatalogoSQL(
                id=id_oferta(catalogo.version, oferta), **valores_oferta(catalogo.version, oferta)
            )
            for oferta in catalogo.ofertas
        )
        self.sesion.flush()
        return True

    def activar(self, version: int) -> None:
        """Desactiva la versión activa y activa `version` en la misma transacción."""
        objetivo = self.sesion.get(CatalogoSQL, version, with_for_update=True)
        if objetivo is None:
            raise ValueError(f"La version {version} del catalogo no existe")
        self.sesion.execute(
            update(CatalogoSQL)
            .where(CatalogoSQL.activo.is_(True), CatalogoSQL.version != version)
            .values(activo=False)
        )
        objetivo.activo = True
        self.sesion.flush()


def _vista_desde_fila(fila: CotizacionSQL) -> VistaCotizacion:
    peticion = fila.peticion
    return VistaCotizacion(
        id_cotizacion=fila.id,
        id_peticion=fila.id_peticion,
        id_trabajo=fila.id_trabajo,
        id_solicitud=fila.id_solicitud,
        id_partner=fila.id_partner,
        categoria=peticion["categoria"],
        tipo_solicitud=TipoSolicitud(peticion["tipo_solicitud"]),
        tipo_red=TipoRed(peticion["tipo_red"]),
        estado=EstadoCotizacion(fila.estado),
        id_proveedor=fila.id_proveedor,
        importe_menor=fila.importe_menor,
        moneda=fila.moneda,
        motivo=MotivoRechazo(fila.motivo) if fila.motivo is not None else None,
        version_catalogo=fila.version_catalogo,
        version_cotizacion=fila.version_cotizacion,
        id_comando_origen=fila.id_comando_origen,
        resuelta_en=fila.resuelta_en,
    )


class RepositorioLecturaCotizacionesSQL:
    """Selecciona columnas directamente hacia VistaCotizacion, sin reconstruir el agregado."""

    def __init__(self, crear_sesion: Callable[[], Session]) -> None:
        self.crear_sesion = crear_sesion

    def obtener(self, id_cotizacion: UUID) -> VistaCotizacion | None:
        with self.crear_sesion() as sesion:
            fila = sesion.get(CotizacionSQL, id_cotizacion)
            return _vista_desde_fila(fila) if fila is not None else None

    def listar(
        self, filtro: FiltroCotizaciones, limite: int, desplazamiento: int
    ) -> list[VistaCotizacion]:
        consulta = select(CotizacionSQL)
        if filtro.id_peticion is not None:
            consulta = consulta.where(CotizacionSQL.id_peticion == filtro.id_peticion)
        if filtro.id_trabajo is not None:
            consulta = consulta.where(CotizacionSQL.id_trabajo == filtro.id_trabajo)
        if filtro.estado is not None:
            consulta = consulta.where(CotizacionSQL.estado == filtro.estado.value)
        consulta = (
            consulta.order_by(CotizacionSQL.resuelta_en, CotizacionSQL.id)
            .limit(limite)
            .offset(desplazamiento)
        )
        with self.crear_sesion() as sesion:
            filas = sesion.scalars(consulta)
            return [_vista_desde_fila(fila) for fila in filas]
