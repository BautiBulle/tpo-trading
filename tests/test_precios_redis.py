"""Pruebas unitarias del repositorio Redis."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.repos.precios_redis import get_precio, set_precio


FECHA = datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)


def test_set_precio_guarda_hash():
    cliente = MagicMock()

    with patch("app.repos.precios_redis.get_redis", return_value=cliente):
        set_precio(
            "AAPL",
            Decimal("185.50"),
            Decimal("185.80"),
            Decimal("185.65"),
            FECHA,
        )

    cliente.hset.assert_called_once_with(
        "precio:AAPL",
        mapping={
            "compra": "185.50",
            "venta": "185.80",
            "ultimo": "185.65",
            "fechaHora": "2026-10-19T18:30:00+00:00",
        },
    )


def test_get_precio_recupera_cotizacion():
    cliente = MagicMock()
    cliente.hgetall.return_value = {
        "compra": "185.50",
        "venta": "185.80",
        "ultimo": "185.65",
        "fechaHora": "2026-10-19T18:30:00+00:00",
    }

    with patch("app.repos.precios_redis.get_redis", return_value=cliente):
        resultado = get_precio("AAPL")

    assert resultado == {
        "compra": Decimal("185.50"),
        "venta": Decimal("185.80"),
        "ultimo": Decimal("185.65"),
        "fechaHora": FECHA,
    }

    cliente.hgetall.assert_called_once_with("precio:AAPL")


def test_get_precio_inexistente():
    cliente = MagicMock()
    cliente.hgetall.return_value = {}

    with patch("app.repos.precios_redis.get_redis", return_value=cliente):
        resultado = get_precio("INEXISTENTE")

    assert resultado is None


@pytest.mark.parametrize("simbolo", ["", "   ", None])
def test_rechazar_simbolo_invalido(simbolo):
    with pytest.raises(ValueError):
        set_precio(
            simbolo,
            Decimal("100"),
            Decimal("101"),
            Decimal("100.50"),
            FECHA,
        )


def test_rechazar_precio_negativo():
    with pytest.raises(ValueError):
        set_precio(
            "AAPL",
            Decimal("-1"),
            Decimal("101"),
            Decimal("100"),
            FECHA,
        )


def test_rechazar_fecha_sin_zona_horaria():
    fecha = datetime(2026, 10, 19, 18, 30)

    with pytest.raises(ValueError):
        set_precio(
            "AAPL",
            Decimal("100"),
            Decimal("101"),
            Decimal("100.50"),
            fecha,
        )


def test_normalizar_fecha_a_utc():
    from datetime import timedelta

    cliente = MagicMock()
    zona = timezone(timedelta(hours=-3))
    fecha_local = datetime(2026, 10, 19, 15, 30, tzinfo=zona)

    with patch("app.repos.precios_redis.get_redis", return_value=cliente):
        set_precio(
            "AAPL",
            Decimal("100"),
            Decimal("101"),
            Decimal("100.50"),
            fecha_local,
        )

    datos = cliente.hset.call_args.kwargs["mapping"]

    assert datos["fechaHora"] == "2026-10-19T18:30:00+00:00"
