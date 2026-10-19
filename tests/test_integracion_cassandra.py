"""Pruebas de integración contra una instancia real de Cassandra."""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.repos import historial_cass


@pytest.fixture(scope="module")
def cassandra_disponible():
    """Comprueba que Cassandra esté inicializada."""
    from app.config import get_cassandra

    if os.getenv("RUN_CASSANDRA_INTEGRATION") != "1":
        pytest.skip("Pruebas de integración no habilitadas")

    sesion = get_cassandra()
    sesion.execute("SELECT * FROM system.local")
    return sesion


def test_integracion_precios(cassandra_disponible):
    instrumento = f"TEST-{uuid4().hex[:12]}"
    fecha = datetime.now(timezone.utc).replace(microsecond=0)

    historial_cass.registrar_precio(
        instrumento,
        fecha,
        Decimal("100.00"),
        Decimal("101.00"),
        Decimal("100.50"),
        1000,
    )

    resultados = historial_cass.consultar_precios(
        instrumento,
        fecha - timedelta(minutes=1),
        fecha + timedelta(minutes=1),
    )

    assert len(resultados) == 1
    assert resultados[0]["precio_ultimo"] == Decimal("100.50")


def test_integracion_operaciones(cassandra_disponible):
    instrumento = f"TEST-{uuid4().hex[:12]}"
    usuario = uuid4()
    operacion = uuid4()
    fecha = datetime.now(timezone.utc).replace(microsecond=0)

    historial_cass.registrar_operacion(
        operacion,
        usuario,
        instrumento,
        fecha,
        "COMPRA",
        Decimal("10"),
        Decimal("150.00"),
    )

    desde = fecha - timedelta(minutes=1)
    hasta = fecha + timedelta(minutes=1)

    por_usuario = historial_cass.consultar_operaciones_usuario(
        usuario, desde, hasta
    )

    por_instrumento = historial_cass.consultar_operaciones_instrumento(
        instrumento, desde, hasta
    )

    assert len(por_usuario) == 1
    assert len(por_instrumento) == 1
    assert por_usuario[0]["id_operacion"] == operacion
    assert por_instrumento[0]["id_operacion"] == operacion
    assert por_usuario[0]["importe"] == Decimal("1500.00")


def test_integracion_auditoria(cassandra_disponible):
    instrumento = f"TEST-{uuid4().hex[:12]}"
    registro = uuid4()
    operador = uuid4()
    fecha = datetime.now(timezone.utc).replace(microsecond=0)

    historial_cass.registrar_auditoria(
        instrumento,
        fecha,
        registro,
        "SUSPENSION",
        "Prueba de integración",
        operador,
    )

    resultados = historial_cass.consultar_auditoria(
        instrumento,
        fecha - timedelta(minutes=1),
        fecha + timedelta(minutes=1),
    )

    assert len(resultados) == 1
    assert resultados[0]["id_registro"] == registro
    assert resultados[0]["accion"] == "SUSPENSION"
