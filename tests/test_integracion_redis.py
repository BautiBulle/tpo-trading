"""Pruebas de integración contra un servidor Redis real."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.config import get_redis
from app.repos.precios_redis import get_precio, set_precio


def test_integracion_guardar_y_consultar_precio():
    simbolo = f"TEST-{uuid4().hex}"
    fecha = datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)
    cliente = get_redis()

    try:
        set_precio(
            simbolo,
            Decimal("185.50"),
            Decimal("185.80"),
            Decimal("185.65"),
            fecha,
        )

        resultado = get_precio(simbolo)

        assert resultado is not None
        assert resultado["compra"] == Decimal("185.50")
        assert resultado["venta"] == Decimal("185.80")
        assert resultado["ultimo"] == Decimal("185.65")
        assert resultado["fechaHora"] == fecha
    finally:
        cliente.delete(f"precio:{simbolo}")


def test_integracion_actualizar_precio():
    simbolo = f"TEST-{uuid4().hex}"
    fecha = datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)
    cliente = get_redis()

    try:
        set_precio(
            simbolo,
            Decimal("100"),
            Decimal("101"),
            Decimal("100.50"),
            fecha,
        )

        set_precio(
            simbolo,
            Decimal("110"),
            Decimal("111"),
            Decimal("110.50"),
            fecha,
        )

        resultado = get_precio(simbolo)

        assert resultado["ultimo"] == Decimal("110.50")
        assert resultado["compra"] == Decimal("110")
    finally:
        cliente.delete(f"precio:{simbolo}")


def test_integracion_precio_inexistente():
    simbolo = f"TEST-{uuid4().hex}"

    assert get_precio(simbolo) is None
