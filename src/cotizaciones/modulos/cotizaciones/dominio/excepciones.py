class ErrorCatalogo(RuntimeError):
    """Error técnico del catálogo: nunca se convierte en un rechazo empresarial."""


class CatalogoNoDisponible(ErrorCatalogo):
    """No hay una versión activa del catálogo."""


class CatalogoInvalido(ErrorCatalogo):
    """Los datos del catálogo violan invariantes del dominio al reconstruirlo."""
