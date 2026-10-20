"""Pruebas de integración de reservas y ejecuciones parciales."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.repos.mongo_repo import (
    crear_orden,
    obtener_orden,
    reservar_ejecucion_orden,
    confirmar_ejecucion_orden,
    liberar_reserva_ejecucion,
)


def nueva_orden():
    id_orden = uuid4()

    crear_orden(
        id_orden=id_orden,
        id_portafolio=uuid4(),
        id_instrumento=uuid4(),
        tipo="COMPRA",
        cantidad=Decimal("10"),
        precio_limite=Decimal("100"),
    )

    return id_orden


def test_reservar_y_confirmar_parcial():
    id_orden = nueva_orden()
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


def test_completar_orden_con_segunda_ejecucion():
    id_orden = nueva_orden()

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


def test_no_permitir_sobre_ejecucion():
    id_orden = nueva_orden()

    reservar_ejecucion_orden(
        id_orden, uuid4(), Decimal("7")
    )

    with pytest.raises(ValueError, match="supera"):
        reservar_ejecucion_orden(
            id_orden, uuid4(), Decimal("4")
        )


def test_liberar_reserva():
    id_orden = nueva_orden()
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


def test_confirmacion_idempotente():
    id_orden = nueva_orden()
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


def test_no_liberar_ejecucion_confirmada():
    id_orden = nueva_orden()
    id_ejecucion = uuid4()

    reservar_ejecucion_orden(
        id_orden, id_ejecucion, Decimal("2")
    )
    confirmar_ejecucion_orden(id_orden, id_ejecucion)

    with pytest.raises(ValueError, match="confirmada"):
        liberar_reserva_ejecucion(
            id_orden, id_ejecucion
        )
