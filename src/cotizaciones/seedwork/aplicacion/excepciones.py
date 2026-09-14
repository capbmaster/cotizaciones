class ColisionPersistencia(RuntimeError):
    pass


class ConflictoMensaje(ValueError):
    """Mismo ID de mensaje con distinto contenido."""
