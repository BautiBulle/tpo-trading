"""Pruebas de integración contra PostgreSQL real."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.config import get_pg
from app.repos.saldo_pg import (
    bloquear,
    consultar_saldo,
    consumir,
    depositar,
    liberar,
    retirar,
)


@pytest.fixture
def portafolio():
    """Crea un identificador único y limpia sus datos al finalizar."""
    identificador = uuid4()

    yield identificador

    conexion = get_pg()

    with conexion.transaction():
        with conexion.cursor() as cur:
            cur.execute(
                "DELETE FROM movimiento_saldo WHERE id_portafolio = %s",
                (identificador,),
            )
            cur.execute(
                "DELETE FROM saldo WHERE id_portafolio = %s",
                (identificador,),
            )


def test_depositar_y_consultar(portafolio):
    assert depositar(portafolio, Decimal("1000.00"), uuid4()) is True

    saldo = consultar_saldo(portafolio)

    assert saldo["disponible"] == Decimal("1000.00")
    assert saldo["bloqueado"] == Decimal("0.00")


def test_retirar(portafolio):
    depositar(portafolio, Decimal("1000.00"), uuid4())

    assert retirar(portafolio, Decimal("250.00"), uuid4()) is True

    saldo = consultar_saldo(portafolio)

    assert saldo["disponible"] == Decimal("750.00")
    assert saldo["bloqueado"] == Decimal("0.00")


def test_bloquear_fondos(portafolio):
    depositar(portafolio, Decimal("1000.00"), uuid4())

    assert bloquear(
        portafolio, Decimal("300.00"), uuid4(), uuid4()
    ) is True

    saldo = consultar_saldo(portafolio)

    assert saldo["disponible"] == Decimal("700.00")
    assert saldo["bloqueado"] == Decimal("300.00")


def test_liberar_fondos(portafolio):
    depositar(portafolio, Decimal("1000.00"), uuid4())

    orden = uuid4()
    bloquear(portafolio, Decimal("300.00"), uuid4(), orden)

    assert liberar(
        portafolio, Decimal("300.00"), uuid4(), orden
    ) is True

    saldo = consultar_saldo(portafolio)

    assert saldo["disponible"] == Decimal("1000.00")
    assert saldo["bloqueado"] == Decimal("0.00")


def test_consumir_fondos(portafolio):
    depositar(portafolio, Decimal("1000.00"), uuid4())

    orden = uuid4()
    bloquear(portafolio, Decimal("300.00"), uuid4(), orden)

    assert consumir(
        portafolio, Decimal("300.00"), uuid4(), orden
    ) is True

    saldo = consultar_saldo(portafolio)

    assert saldo["disponible"] == Decimal("700.00")
    assert saldo["bloqueado"] == Decimal("0.00")


def test_rechazar_saldo_insuficiente(portafolio):
    depositar(portafolio, Decimal("100.00"), uuid4())

    with pytest.raises(ValueError, match="Saldo disponible insuficiente"):
        retirar(portafolio, Decimal("200.00"), uuid4())

    saldo = consultar_saldo(portafolio)

    assert saldo["disponible"] == Decimal("100.00")


def test_idempotencia(portafolio):
    operacion = uuid4()

    assert depositar(
        portafolio, Decimal("500.00"), operacion
    ) is True

    assert depositar(
        portafolio, Decimal("500.00"), operacion
    ) is False

    saldo = consultar_saldo(portafolio)

    assert saldo["disponible"] == Decimal("500.00")


def test_rechazar_repeticion_con_importe_diferente(portafolio):
    operacion = uuid4()

    depositar(portafolio, Decimal("500.00"), operacion)

    with pytest.raises(
        ValueError, match="Operación repetida con datos diferentes"
    ):
        depositar(portafolio, Decimal("600.00"), operacion)

    saldo = consultar_saldo(portafolio)

    assert saldo["disponible"] == Decimal("500.00")


def test_rollback_por_error(portafolio):
    depositar(portafolio, Decimal("100.00"), uuid4())

    with pytest.raises(ValueError):
        bloquear(
            portafolio, Decimal("500.00"), uuid4(), uuid4()
        )

    saldo = consultar_saldo(portafolio)

    assert saldo["disponible"] == Decimal("100.00")
    assert saldo["bloqueado"] == Decimal("0.00")


def test_consultar_portafolio_inexistente():
    assert consultar_saldo(uuid4()) is None
