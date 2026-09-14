from datetime import UTC, datetime


class RelojActual:
    def ahora(self) -> datetime:
        return datetime.now(UTC)
