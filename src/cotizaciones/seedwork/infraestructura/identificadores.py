from uuid import UUID, uuid4


class IdentificadoresAleatorios:
    def generar(self) -> UUID:
        return uuid4()
