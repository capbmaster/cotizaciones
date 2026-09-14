from datetime import datetime
from uuid import UUID


def validar_identidad(valor: object) -> None:
    if not isinstance(valor, UUID) or valor.int == 0:
        raise ValueError("La identidad debe ser un UUID no nulo")


def validar_instante(valor: object) -> None:
    if not isinstance(valor, datetime) or valor.utcoffset() is None:
        raise ValueError("El instante debe incluir zona horaria")


def validar_version(valor: object) -> None:
    if type(valor) is not int or valor < 1:
        raise ValueError("La version debe ser un entero positivo")


def validar_texto(valor: object) -> None:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError("El texto debe contener al menos un caracter visible")
