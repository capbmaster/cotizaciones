from datetime import datetime
from typing import Any
from uuid import UUID

Documento = dict[str, Any]


def texto(documento: Documento, campo: str) -> str:
    valor = documento[campo]
    if not isinstance(valor, str):
        raise ValueError(f"{campo} debe ser texto")
    return valor


def entero(documento: Documento, campo: str) -> int:
    valor = documento[campo]
    if type(valor) is not int:
        raise ValueError(f"{campo} debe ser entero")
    return valor


def objeto(documento: Documento, campo: str) -> Documento:
    valor = documento[campo]
    if not isinstance(valor, dict):
        raise ValueError(f"{campo} debe ser objeto")
    return valor


def identidad(documento: Documento, campo: str) -> UUID:
    return UUID(texto(documento, campo))


def instante(documento: Documento, campo: str) -> datetime:
    return datetime.fromisoformat(texto(documento, campo))
