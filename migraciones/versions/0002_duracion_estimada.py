from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_CHECK = "duracion_estimada_minutos IS NULL OR duracion_estimada_minutos > 0"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE cotizaciones.ofertas_catalogo "
        "ADD COLUMN duracion_estimada_minutos INTEGER "
        f"CONSTRAINT ck_oferta_duracion CHECK ({_CHECK})"
    )
    op.execute(
        "ALTER TABLE cotizaciones.cotizaciones "
        "ADD COLUMN duracion_estimada_minutos INTEGER "
        f"CONSTRAINT ck_cotizacion_duracion CHECK ({_CHECK})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE cotizaciones.cotizaciones DROP COLUMN duracion_estimada_minutos")
    op.execute("ALTER TABLE cotizaciones.ofertas_catalogo DROP COLUMN duracion_estimada_minutos")
