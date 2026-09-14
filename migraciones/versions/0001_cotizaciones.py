from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA cotizaciones")
    op.execute("CREATE SCHEMA mensajeria")
    op.execute("""CREATE TABLE cotizaciones.catalogos (
        version INTEGER PRIMARY KEY,
        huella TEXT NOT NULL,
        cargado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
        activo BOOLEAN NOT NULL DEFAULT false,
        CONSTRAINT ck_catalogo_version CHECK (version > 0)
    )""")
    op.execute(
        "CREATE UNIQUE INDEX uq_catalogo_activo ON cotizaciones.catalogos (activo) WHERE activo"
    )
    op.execute("""CREATE TABLE cotizaciones.ofertas_catalogo (
        id UUID PRIMARY KEY,
        version_catalogo INTEGER NOT NULL,
        id_proveedor UUID NOT NULL,
        categoria TEXT NOT NULL,
        tipo_red TEXT NOT NULL,
        id_partner UUID,
        importe_menor BIGINT NOT NULL,
        moneda TEXT NOT NULL,
        CONSTRAINT fk_oferta_catalogo FOREIGN KEY (version_catalogo)
            REFERENCES cotizaciones.catalogos (version),
        CONSTRAINT ck_oferta_tipo_red CHECK (tipo_red IN ('GENERAL_HDA', 'HOMOLOGADA_PARTNER')),
        CONSTRAINT ck_oferta_importe CHECK (importe_menor > 0),
        CONSTRAINT ck_oferta_moneda CHECK (moneda ~ '^[A-Z]{3}$'),
        CONSTRAINT ck_oferta_red_partner CHECK (
            (tipo_red <> 'GENERAL_HDA' OR id_partner IS NULL)
            AND (tipo_red <> 'HOMOLOGADA_PARTNER' OR id_partner IS NOT NULL)),
        CONSTRAINT uq_oferta_catalogo UNIQUE NULLS NOT DISTINCT
            (version_catalogo, categoria, tipo_red, id_partner, id_proveedor)
    )""")
    op.execute(
        "CREATE INDEX ix_oferta_version_categoria "
        "ON cotizaciones.ofertas_catalogo (version_catalogo, categoria)"
    )
    op.execute("""CREATE TABLE cotizaciones.cotizaciones (
        id UUID PRIMARY KEY,
        id_peticion UUID NOT NULL,
        id_trabajo UUID NOT NULL,
        id_solicitud UUID NOT NULL,
        id_partner UUID NOT NULL,
        peticion JSONB NOT NULL,
        id_comando_origen UUID NOT NULL,
        correlacion UUID NOT NULL,
        causacion UUID NOT NULL,
        instante_comando TIMESTAMPTZ NOT NULL,
        version_catalogo INTEGER NOT NULL,
        version_cotizacion INTEGER NOT NULL,
        estado TEXT NOT NULL,
        id_proveedor UUID,
        importe_menor BIGINT,
        moneda TEXT,
        motivo TEXT,
        resuelta_en TIMESTAMPTZ NOT NULL,
        registrada_en TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_cotizacion_peticion UNIQUE (id_peticion),
        CONSTRAINT fk_cotizacion_catalogo FOREIGN KEY (version_catalogo)
            REFERENCES cotizaciones.catalogos (version),
        CONSTRAINT ck_cotizacion_version CHECK (version_cotizacion = 1),
        CONSTRAINT ck_cotizacion_estado CHECK (estado IN ('PROPUESTA', 'RECHAZADA')),
        CONSTRAINT ck_cotizacion_motivo CHECK (
            motivo IS NULL OR motivo IN ('SIN_OFERTA_PARA_CATEGORIA', 'SIN_PROVEEDOR_EN_RED')),
        CONSTRAINT ck_cotizacion_resultado CHECK (
            (estado = 'PROPUESTA' AND id_proveedor IS NOT NULL AND importe_menor IS NOT NULL
             AND importe_menor > 0 AND moneda IS NOT NULL AND motivo IS NULL)
            OR (estado = 'RECHAZADA' AND id_proveedor IS NULL AND importe_menor IS NULL
                AND moneda IS NULL AND motivo IS NOT NULL))
    )""")
    op.execute("CREATE INDEX ix_cotizacion_trabajo ON cotizaciones.cotizaciones (id_trabajo)")
    op.execute("CREATE INDEX ix_cotizacion_resuelta ON cotizaciones.cotizaciones (resuelta_en, id)")
    op.execute("""CREATE TABLE mensajeria.inbox (
        nombre_consumidor TEXT NOT NULL,
        id_mensaje UUID NOT NULL,
        documento JSONB NOT NULL,
        procesada_en TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (nombre_consumidor, id_mensaje)
    )""")
    op.execute("""CREATE TABLE mensajeria.outbox (
        id UUID PRIMARY KEY, id_evento UUID NOT NULL, destino TEXT NOT NULL,
        documento JSONB NOT NULL,
        creada_en TIMESTAMPTZ NOT NULL DEFAULT now(),
        proximo_intento TIMESTAMPTZ NOT NULL DEFAULT now(),
        enviada_en TIMESTAMPTZ, propietario TEXT, token UUID, vence_en TIMESTAMPTZ,
        intentos INTEGER NOT NULL DEFAULT 0, ultimo_error TEXT,
        CONSTRAINT uq_salida_destino UNIQUE (id_evento, destino)
    )""")
    op.execute(
        "CREATE INDEX ix_salida_pendiente ON mensajeria.outbox "
        "(enviada_en, proximo_intento, vence_en)"
    )
    op.execute("""CREATE TABLE mensajeria.eventos (
        id_evento UUID PRIMARY KEY, documento JSONB NOT NULL
    )""")


def downgrade() -> None:
    op.execute("DROP TABLE mensajeria.eventos")
    op.execute("DROP TABLE mensajeria.outbox")
    op.execute("DROP TABLE mensajeria.inbox")
    op.execute("DROP TABLE cotizaciones.cotizaciones")
    op.execute("DROP TABLE cotizaciones.ofertas_catalogo")
    op.execute("DROP TABLE cotizaciones.catalogos")
    op.execute("DROP SCHEMA mensajeria")
    op.execute("DROP SCHEMA cotizaciones")
