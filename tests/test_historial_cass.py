
"""Pruebas unitarias del repositorio Cassandra."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.repos import historial_cass


@pytest.fixture
def sesion_falsa(monkeypatch):
    """Reemplaza Cassandra por una sesión simulada."""
    sesion = MagicMock()
    monkeypatch.setattr(historial_cass, "get_cassandra", lambda: sesion)
    return sesion


def test_registrar_precio(sesion_falsa):
    fecha = datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc)

    historial_cass.registrar_precio(
        "AAPL",
        fecha,
        Decimal("100"),
        Decimal("101"),
        Decimal("100.50"),
        1000,
    )

    sesion_falsa.execute.assert_called_once()

    parametros = sesion_falsa.execute.call_args.args[1]

    assert parametros[0] == "AAPL"
    assert parametros[1] == fecha.date()
    assert parametros[2] == fecha
    assert parametros[5] == Decimal("100.50")


def test_consultar_precios_varios_dias(sesion_falsa):
    sesion_falsa.execute.return_value = []

    desde = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
    hasta = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)

    resultado = historial_cass.consultar_precios(
        "AAPL", desde, hasta
    )

    assert resultado == []
    assert sesion_falsa.execute.call_count == 3

    dias = [
        llamada.args[1][1]
        for llamada in sesion_falsa.execute.call_args_list
    ]

    assert [dia.isoformat() for dia in dias] == [
        "2026-10-18",
        "2026-10-19",
        "2026-10-20",
    ]


def test_registrar_operacion_en_dos_tablas(sesion_falsa):
    id_operacion = uuid4()
    id_usuario = uuid4()
    fecha = datetime(2026, 10, 19, 14, tzinfo=timezone.utc)

    historial_cass.registrar_operacion(
        id_operacion,
        id_usuario,
        "AAPL",
        fecha,
        "COMPRA",
        Decimal("10"),
        Decimal("150"),
    )

    assert sesion_falsa.execute.call_count == 2

    parametros_usuario = (
        sesion_falsa.execute.call_args_list[0].args[1]
    )
    parametros_instrumento = (
        sesion_falsa.execute.call_args_list[1].args[1]
    )

    assert parametros_usuario[1] == "2026-10"
    assert parametros_usuario[3] == id_operacion
    assert parametros_usuario[8] == Decimal("1500")

    assert parametros_instrumento[1] == fecha.date()
    assert parametros_instrumento[3] == id_operacion


def test_consultar_operaciones_usuario(sesion_falsa):
    sesion_falsa.execute.return_value = []

    usuario = uuid4()
    desde = datetime(2026, 9, 1, tzinfo=timezone.utc)
    hasta = datetime(2026, 11, 1, tzinfo=timezone.utc)

    resultado = historial_cass.consultar_operaciones_usuario(
        usuario, desde, hasta
    )

    assert resultado == []
    assert sesion_falsa.execute.call_count == 3


def test_consultar_operaciones_instrumento(sesion_falsa):
    sesion_falsa.execute.return_value = []

    desde = datetime(2026, 10, 18, tzinfo=timezone.utc)
    hasta = datetime(2026, 10, 20, tzinfo=timezone.utc)

    resultado = historial_cass.consultar_operaciones_instrumento(
        "AAPL", desde, hasta
    )

    assert resultado == []
    # El intervalo termina al inicio del día 20.
    assert sesion_falsa.execute.call_count == 2


def test_registrar_auditoria(sesion_falsa):
    id_registro = uuid4()
    id_operador = uuid4()
    fecha = datetime(2026, 10, 19, tzinfo=timezone.utc)

    historial_cass.registrar_auditoria(
        "AAPL",
        fecha,
        id_registro,
        "SUSPENSION",
        "Suspensión administrativa",
        id_operador,
    )

    sesion_falsa.execute.assert_called_once()

    parametros = sesion_falsa.execute.call_args.args[1]

    assert parametros[0] == "AAPL"
    assert parametros[2] == id_registro
    assert parametros[3] == "SUSPENSION"
    assert parametros[5] == id_operador


def test_rechazar_fechas_sin_zona_horaria(sesion_falsa):
    fecha_sin_zona = datetime(2026, 10, 19, 10)

    with pytest.raises(ValueError):
        historial_cass.registrar_precio(
            "AAPL",
            fecha_sin_zona,
            Decimal("100"),
            Decimal("101"),
            Decimal("100.50"),
            1000,
        )

    sesion_falsa.execute.assert_not_called()


def test_rechazar_operacion_invalida(sesion_falsa):
    with pytest.raises(ValueError):
        historial_cass.registrar_operacion(
            uuid4(),
            uuid4(),
            "AAPL",
            datetime(2026, 10, 19, tzinfo=timezone.utc),
            "COMPRA",
            Decimal("-5"),
            Decimal("100"),
        )

    sesion_falsa.execute.assert_not_called()
