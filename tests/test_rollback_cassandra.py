"""Pruebas reales del rollback de operaciones en Cassandra."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.config import get_cassandra
from app.repos.historial_cass import (
    registrar_operacion,
    revertir_operacion,
)


def _buscar_operacion(id_operacion, id_usuario, simbolo, fecha):
    sesion = get_cassandra()
    mes = fecha.strftime("%Y-%m")
    dia = fecha.date()

    consulta_usuario = sesion.prepare("""
        SELECT id_operacion
        FROM operaciones_por_usuario
        WHERE id_usuario = ?
          AND mes = ?
          AND fecha_hora = ?
          AND id_operacion = ?
    """)

    consulta_instrumento = sesion.prepare("""
        SELECT id_operacion
        FROM operaciones_por_instrumento
        WHERE id_instrumento = ?
          AND dia = ?
          AND fecha_hora = ?
          AND id_operacion = ?
    """)

    por_usuario = sesion.execute(
        consulta_usuario,
        (id_usuario, mes, fecha, id_operacion),
    ).one()

    por_instrumento = sesion.execute(
        consulta_instrumento,
        (simbolo, dia, fecha, id_operacion),
    ).one()

    return por_usuario, por_instrumento


def test_registrar_y_revertir_operacion():
    id_operacion = uuid4()
    id_usuario = uuid4()
    simbolo = "ACT001"
    fecha = datetime.now(timezone.utc)

    registrar_operacion(
        id_operacion,
        id_usuario,
        simbolo,
        fecha,
        "COMPRA",
        Decimal("2"),
        Decimal("100"),
    )

    usuario, instrumento = _buscar_operacion(
        id_operacion, id_usuario, simbolo, fecha
    )

    assert usuario is not None
    assert instrumento is not None

    revertir_operacion(
        id_operacion, id_usuario, simbolo, fecha
    )

    usuario, instrumento = _buscar_operacion(
        id_operacion, id_usuario, simbolo, fecha
    )

    assert usuario is None
    assert instrumento is None


def test_rollback_idempotente():
    id_operacion = uuid4()
    id_usuario = uuid4()
    simbolo = "ACT002"
    fecha = datetime.now(timezone.utc)

    registrar_operacion(
        id_operacion,
        id_usuario,
        simbolo,
        fecha,
        "COMPRA",
        Decimal("3"),
        Decimal("150"),
    )

    revertir_operacion(
        id_operacion, id_usuario, simbolo, fecha
    )

    # Repetir el rollback no debe generar errores.
    revertir_operacion(
        id_operacion, id_usuario, simbolo, fecha
    )

    usuario, instrumento = _buscar_operacion(
        id_operacion, id_usuario, simbolo, fecha
    )

    assert usuario is None
    assert instrumento is None


def test_rollback_de_operacion_inexistente():
    id_operacion = uuid4()
    id_usuario = uuid4()
    simbolo = "ACT003"
    fecha = datetime.now(timezone.utc)

    # Debe poder compensarse incluso si la escritura
    # original nunca llegó a completarse.
    revertir_operacion(
        id_operacion, id_usuario, simbolo, fecha
    )

    usuario, instrumento = _buscar_operacion(
        id_operacion, id_usuario, simbolo, fecha
    )

    assert usuario is None
    assert instrumento is None
