"""Pruebas de integración de consumo y reversión en PostgreSQL."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.repos.saldo_pg import (
    depositar,
    bloquear,
    consumir,
    revertir_consumo,
    consultar_saldo,
)


def preparar_portafolio():
    """Crea un saldo independiente para cada prueba."""
    id_portafolio = uuid4()
    id_orden = uuid4()

    depositar(
        id_portafolio,
        Decimal("1000.00"),
        uuid4(),
    )

    bloquear(
        id_portafolio,
        Decimal("500.00"),
        uuid4(),
        id_orden,
    )

    return id_portafolio, id_orden


def test_consumo_y_reversion_restauran_saldo():
    id_portafolio, id_orden = preparar_portafolio()
    id_operacion = uuid4()

    saldo_antes = consultar_saldo(id_portafolio)

    assert consumir(
        id_portafolio,
        Decimal("200.00"),
        id_operacion,
        id_orden,
    ) is True

    saldo_consumido = consultar_saldo(id_portafolio)

    assert saldo_consumido["disponible"] == Decimal("500.00")
    assert saldo_consumido["bloqueado"] == Decimal("300.00")

    assert revertir_consumo(
        id_portafolio,
        Decimal("200.00"),
        id_operacion,
        id_orden,
    ) is True

    assert consultar_saldo(id_portafolio) == saldo_antes


def test_reversion_idempotente():
    id_portafolio, id_orden = preparar_portafolio()
    id_operacion = uuid4()

    consumir(
        id_portafolio,
        Decimal("100.00"),
        id_operacion,
        id_orden,
    )

    assert revertir_consumo(
        id_portafolio,
        Decimal("100.00"),
        id_operacion,
        id_orden,
    ) is True

    assert revertir_consumo(
        id_portafolio,
        Decimal("100.00"),
        id_operacion,
        id_orden,
    ) is False

    saldo = consultar_saldo(id_portafolio)

    assert saldo["disponible"] == Decimal("500.00")
    assert saldo["bloqueado"] == Decimal("500.00")


def test_no_revertir_consumo_inexistente():
    id_portafolio, id_orden = preparar_portafolio()
    saldo_antes = consultar_saldo(id_portafolio)

    with pytest.raises(ValueError, match="No existe un consumo"):
        revertir_consumo(
            id_portafolio,
            Decimal("100.00"),
            uuid4(),
            id_orden,
        )

    assert consultar_saldo(id_portafolio) == saldo_antes


def test_no_revertir_importe_diferente():
    id_portafolio, id_orden = preparar_portafolio()
    id_operacion = uuid4()

    consumir(
        id_portafolio,
        Decimal("200.00"),
        id_operacion,
        id_orden,
    )

    saldo_antes = consultar_saldo(id_portafolio)

    with pytest.raises(ValueError, match="no coincide"):
        revertir_consumo(
            id_portafolio,
            Decimal("150.00"),
            id_operacion,
            id_orden,
        )

    assert consultar_saldo(id_portafolio) == saldo_antes
