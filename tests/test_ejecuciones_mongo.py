"""Pruebas de integración de reservas y ejecuciones parciales."""

from decimal import Decimal
from uuid import uuid4

import pytest
from app.config import get_mongo_db

from app.repos.mongo_repo import (
    crear_instrumento,
    crear_orden,
    obtener_orden,
    reservar_ejecucion_orden,
    confirmar_ejecucion_orden,
    liberar_reserva_ejecucion,
)



@pytest.fixture
def limpieza_mongo():
    """Elimina los documentos creados por cada prueba."""
    creados = []
    yield creados

    db = get_mongo_db()
    for coleccion, identificador in reversed(creados):
        db[coleccion].delete_one({"_id": str(identificador)})


def nueva_orden(limpieza_mongo):
    id_orden = uuid4()
    id_instrumento = uuid4()

    limpieza_mongo.append(("instrumentos", id_instrumento))
    limpieza_mongo.append(("ordenes", id_orden))

    crear_instrumento(
        id_instrumento,
        f"TEST-{uuid4().hex[:12]}",
        "Instrumento de prueba",
        "Tecnologia",
    )

    crear_orden(
        id_orden=id_orden,
        id_portafolio=uuid4(),
        id_instrumento=id_instrumento,
        tipo="COMPRA",
        cantidad=Decimal("10"),
        precio_limite=Decimal("100"),
    )

    return id_orden


def test_reservar_y_confirmar_parcial(limpieza_mongo):
    id_orden = nueva_orden(limpieza_mongo)
    id_ejecucion = uuid4()

    assert reservar_ejecucion_orden(
        id_orden, id_ejecucion, Decimal("4")
    ) is True

    assert confirmar_ejecucion_orden(
        id_orden, id_ejecucion
    ) is True

    orden = obtener_orden(id_orden)

    assert orden["cantidadEjecutada"] == Decimal("4")
    assert orden["estado"] == "PARCIALMENTE_EJECUTADA"


def test_completar_orden_con_segunda_ejecucion(limpieza_mongo):
    id_orden = nueva_orden(limpieza_mongo)

    primera = uuid4()
    segunda = uuid4()

    reservar_ejecucion_orden(
        id_orden, primera, Decimal("4")
    )
    confirmar_ejecucion_orden(id_orden, primera)

    reservar_ejecucion_orden(
        id_orden, segunda, Decimal("6")
    )
    confirmar_ejecucion_orden(id_orden, segunda)

    orden = obtener_orden(id_orden)

    assert orden["cantidadEjecutada"] == Decimal("10")
    assert orden["estado"] == "EJECUTADA"


def test_no_permitir_sobre_ejecucion(limpieza_mongo):
    id_orden = nueva_orden(limpieza_mongo)

    reservar_ejecucion_orden(
        id_orden, uuid4(), Decimal("7")
    )

    with pytest.raises(ValueError, match="supera"):
        reservar_ejecucion_orden(
            id_orden, uuid4(), Decimal("4")
        )


def test_liberar_reserva(limpieza_mongo):
    id_orden = nueva_orden(limpieza_mongo)
    id_ejecucion = uuid4()

    reservar_ejecucion_orden(
        id_orden, id_ejecucion, Decimal("5")
    )

    assert liberar_reserva_ejecucion(
        id_orden, id_ejecucion
    ) is True

    assert liberar_reserva_ejecucion(
        id_orden, id_ejecucion
    ) is False

    orden = obtener_orden(id_orden)

    assert orden["cantidadEjecutada"] == Decimal("0")
    assert orden["estado"] == "PENDIENTE"

    # La cantidad liberada vuelve a estar disponible.
    assert reservar_ejecucion_orden(
        id_orden, uuid4(), Decimal("10")
    ) is True


def test_confirmacion_idempotente(limpieza_mongo):
    id_orden = nueva_orden(limpieza_mongo)
    id_ejecucion = uuid4()

    reservar_ejecucion_orden(
        id_orden, id_ejecucion, Decimal("3")
    )

    assert confirmar_ejecucion_orden(
        id_orden, id_ejecucion
    ) is True

    assert confirmar_ejecucion_orden(
        id_orden, id_ejecucion
    ) is False

    orden = obtener_orden(id_orden)

    assert orden["cantidadEjecutada"] == Decimal("3")


def test_no_liberar_ejecucion_confirmada(limpieza_mongo):
    id_orden = nueva_orden(limpieza_mongo)
    id_ejecucion = uuid4()

    reservar_ejecucion_orden(
        id_orden, id_ejecucion, Decimal("2")
    )
    confirmar_ejecucion_orden(id_orden, id_ejecucion)

    with pytest.raises(ValueError, match="confirmada"):
        liberar_reserva_ejecucion(
            id_orden, id_ejecucion
        )
