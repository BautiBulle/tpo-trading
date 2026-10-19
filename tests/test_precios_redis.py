"""Pruebas unitarias del repositorio Redis."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.repos.precios_redis import get_precio, set_precio


FECHA = datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc)


def guardar_precio(cliente, fecha=FECHA):
    with patch("app.repos.precios_redis.get_redis", return_value=cliente):
        set_precio(
            "AAPL",
            Decimal("185.50"),
            Decimal("185.80"),
            Decimal("185.65"),
            fecha,
        )


def test_set_precio_guarda_hash():
    cliente = MagicMock()
    guardar_precio(cliente)

    cliente.eval.assert_called_once()

    argumentos = cliente.eval.call_args.args
    assert argumentos[1] == 1
    assert argumentos[2] == "precio:AAPL"
    assert argumentos[4:] == (
        "185.50",
        "185.80",
        "185.65",
        "2026-10-19T18:30:00+00:00",
    )


def test_set_precio_utiliza_actualizacion_atomica():
    cliente = MagicMock()
    guardar_precio(cliente)

    script = cliente.eval.call_args.args[0]

    assert "HGET" in script
    assert "HSET" in script
    assert "timestamp_ns" in script
    cliente.hset.assert_not_called()


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
    cliente = MagicMock()
    zona = timezone(timedelta(hours=-3))
    fecha_local = datetime(2026, 10, 19, 15, 30, tzinfo=zona)

    guardar_precio(cliente, fecha_local)

    argumentos = cliente.eval.call_args.args
    assert argumentos[7] == "2026-10-19T18:30:00+00:00"


def test_timestamp_mas_reciente_es_mayor():
    cliente = MagicMock()

    guardar_precio(cliente, FECHA)
    anterior = cliente.eval.call_args.args[3]

    guardar_precio(cliente, FECHA + timedelta(minutes=1))
    posterior = cliente.eval.call_args.args[3]

    assert posterior > anterior


def test_timestamp_igual_para_mismo_instante():
    cliente = MagicMock()
    zona = timezone(timedelta(hours=-3))

    guardar_precio(cliente, FECHA)
    timestamp_utc = cliente.eval.call_args.args[3]

    guardar_precio(cliente, FECHA.astimezone(zona))
    timestamp_local = cliente.eval.call_args.args[3]

    assert timestamp_utc == timestamp_local
