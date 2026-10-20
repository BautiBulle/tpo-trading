"""Pruebas de integración de posiciones MongoDB."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.config import get_mongo_db
from app.repos.posiciones_mongo import (
    aplicar_compra,
    obtener_posicion,
    revertir_compra,
)


@pytest.fixture
def ids():
    return {
        "portafolio": uuid4(),
        "instrumento": uuid4(),
        "ejecucion": uuid4(),
    }


def test_compra_crea_posicion(ids):
    resultado = aplicar_compra(
        ids["portafolio"],
        ids["instrumento"],
        Decimal("5"),
        Decimal("100"),
        ids["ejecucion"],
    )

    posicion = obtener_posicion(
        ids["portafolio"], ids["instrumento"]
    )

    assert resultado is True
    assert posicion["cantidad"].to_decimal() == Decimal("5")
    assert posicion["precioPromedio"].to_decimal() == Decimal("100")


def test_compra_idempotente(ids):
    argumentos = (
        ids["portafolio"],
        ids["instrumento"],
        Decimal("5"),
        Decimal("100"),
        ids["ejecucion"],
    )

    assert aplicar_compra(*argumentos) is True
    assert aplicar_compra(*argumentos) is False

    posicion = obtener_posicion(
        ids["portafolio"], ids["instrumento"]
    )
    assert posicion["cantidad"].to_decimal() == Decimal("5")


def test_precio_promedio_ponderado(ids):
    aplicar_compra(
        ids["portafolio"],
        ids["instrumento"],
        Decimal("2"),
        Decimal("100"),
        uuid4(),
    )

    aplicar_compra(
        ids["portafolio"],
        ids["instrumento"],
        Decimal("2"),
        Decimal("200"),
        uuid4(),
    )

    posicion = obtener_posicion(
        ids["portafolio"], ids["instrumento"]
    )

    assert posicion["cantidad"].to_decimal() == Decimal("4")
    assert posicion["precioPromedio"].to_decimal() == Decimal("150")


def test_rollback_restaura_posicion(ids):
    aplicar_compra(
        ids["portafolio"],
        ids["instrumento"],
        Decimal("3"),
        Decimal("120"),
        ids["ejecucion"],
    )

    assert revertir_compra(ids["ejecucion"]) is True

    posicion = obtener_posicion(
        ids["portafolio"], ids["instrumento"]
    )

    assert posicion["cantidad"].to_decimal() == Decimal("0")
    assert posicion["precioPromedio"].to_decimal() == Decimal("0")

    assert revertir_compra(ids["ejecucion"]) is False


def test_rollback_no_pisa_movimiento_posterior(ids):
    aplicar_compra(
        ids["portafolio"],
        ids["instrumento"],
        Decimal("3"),
        Decimal("100"),
        ids["ejecucion"],
    )

    aplicar_compra(
        ids["portafolio"],
        ids["instrumento"],
        Decimal("2"),
        Decimal("150"),
        uuid4(),
    )

    with pytest.raises(RuntimeError):
        revertir_compra(ids["ejecucion"])

    posicion = obtener_posicion(
        ids["portafolio"], ids["instrumento"]
    )

    assert posicion["cantidad"].to_decimal() == Decimal("5")
