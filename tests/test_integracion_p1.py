"""Integración del Problema 1: Redis y Cassandra."""

from datetime import timedelta
from decimal import Decimal

from app.problemas.p1_cotizaciones import (
    publicar_cotizacion,
    ejecutar_publicador,
)
from app.repos.precios_redis import get_precio
from app.repos.historial_cass import consultar_precios


def test_publicar_cotizacion_en_redis_y_cassandra():
    simbolo = "ACT001"

    cotizacion = publicar_cotizacion(
        simbolo,
        Decimal("100.00"),
        Decimal("101.00"),
        Decimal("100.50"),
    )

    actual = get_precio(simbolo)

    assert actual is not None
    assert actual["compra"] == Decimal("100.00")
    assert actual["venta"] == Decimal("101.00")
    assert actual["ultimo"] == Decimal("100.50")
    assert actual["fechaHora"] == cotizacion["fechaHora"]

    
    historico = consultar_precios(
        simbolo,
        cotizacion["fechaHora"] - timedelta(seconds=1),
        cotizacion["fechaHora"] + timedelta(seconds=1),
    )


    assert any(
        precio["precio_ultimo"] == Decimal("100.50")
        for precio in historico
    )



def test_publicador_actualiza_120_instrumentos():
    total = ejecutar_publicador(
        cantidad_instrumentos=120,
        rondas=2,
        pausa=0,
    )

    assert total == 240

    for numero in range(1, 121):
        simbolo = f"ACT{numero:03d}"
        assert get_precio(simbolo) is not None
