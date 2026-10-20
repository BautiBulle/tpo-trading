"""Pruebas de integración del Problema 3 con las tres bases."""

from decimal import Decimal
from uuid import uuid4
from app.repos.historial_cass import consultar_operaciones_usuario

import pytest


from app.config import get_mongo_db
from app.problemas.p3_ejecucion import ejecutar_orden_compra
from app.repos.mongo_repo import (
    crear_usuario,
    crear_instrumento,
    crear_portafolio,
    crear_orden,
    obtener_orden,
    obtener_saga,
)
from app.repos.posiciones_mongo import obtener_posicion
from app.repos.saldo_pg import (
    depositar,
    bloquear,
    consultar_saldo,
)


@pytest.fixture
def escenario():
    usuario = uuid4()
    portafolio = uuid4()
    instrumento = uuid4()
    orden = uuid4()

    crear_usuario(
        usuario,
        "Usuario prueba P3",
        f"p3-{usuario}@test.local",
    )
    crear_portafolio(portafolio, usuario)
    crear_instrumento(
        instrumento,
        f"P3{str(instrumento)[:8]}",
        "Instrumento prueba P3",
        "TECNOLOGIA",
    )
    crear_orden(
        orden,
        portafolio,
        instrumento,
        "COMPRA",
        Decimal("10"),
        Decimal("100.00"),
    )

    depositar(portafolio, Decimal("2000.00"), uuid4())
    bloquear(portafolio, Decimal("1000.00"), uuid4(), orden)

    return {
        "usuario": usuario,
        "portafolio": portafolio,
        "instrumento": instrumento,
        "orden": orden,
    }


def test_ejecucion_parcial_y_total(escenario):
    orden_id = escenario["orden"]

    primera = ejecutar_orden_compra(
        orden_id,
        Decimal("4"),
    )

    assert primera["estado"] == "PARCIALMENTE_EJECUTADA"
    assert primera["cantidadEjecutada"] == Decimal("4")

    segunda = ejecutar_orden_compra(
        orden_id,
        Decimal("6"),
    )

    assert segunda["estado"] == "EJECUTADA"
    assert segunda["cantidadEjecutada"] == Decimal("10")

    posicion = obtener_posicion(
        escenario["portafolio"],
        escenario["instrumento"],
    )

    assert posicion["cantidad"].to_decimal() == Decimal("10")

    saldo = consultar_saldo(escenario["portafolio"])

    assert saldo["disponible"] == Decimal("1000.00")
    assert saldo["bloqueado"] == Decimal("0.00")


@pytest.mark.parametrize(
    "falla",
    ["POSICION", "HISTORIAL", "SALDO"],
)
def test_rollback_completo(escenario, falla):
    id_ejecucion = uuid4()

    saldo_inicial = consultar_saldo(escenario["portafolio"])

    with pytest.raises(RuntimeError, match="Falla simulada"):
        ejecutar_orden_compra(
            escenario["orden"],
            Decimal("3"),
            id_ejecucion=id_ejecucion,
            forzar_falla=falla,
        )

    orden = obtener_orden(escenario["orden"])

    assert orden["estado"] == "PENDIENTE"
    assert orden["cantidadEjecutada"] == Decimal("0")
    assert orden.get("reservasEjecucion", []) == []

    posicion = obtener_posicion(
        escenario["portafolio"],
        escenario["instrumento"],
    )

    assert posicion is None or (
        posicion["cantidad"].to_decimal() == Decimal("0")
    )

    assert consultar_saldo(escenario["portafolio"]) == saldo_inicial
        operaciones = consultar_operaciones_usuario(
        escenario["usuario"],
    )

    assert not any(
        str(op["id_operacion"]) == str(id_ejecucion)
        for op in operaciones
    )

    saga = obtener_saga(id_ejecucion)

    assert saga is not None
    assert saga["estado"] == "COMPENSADA"


def test_no_ejecutar_mas_de_lo_pendiente(escenario):
    with pytest.raises(ValueError, match="supera"):
        ejecutar_orden_compra(
            escenario["orden"],
            Decimal("11"),
        )

    orden = obtener_orden(escenario["orden"])

    assert orden["cantidadEjecutada"] == Decimal("0")
    assert orden["estado"] == "PENDIENTE"


def test_reintento_de_ejecucion_confirmada(escenario):
    id_ejecucion = uuid4()

    primera = ejecutar_orden_compra(
        escenario["orden"],
        Decimal("2"),
        id_ejecucion=id_ejecucion,
    )

    segunda = ejecutar_orden_compra(
        escenario["orden"],
        Decimal("2"),
        id_ejecucion=id_ejecucion,
    )

    assert primera["cantidadEjecutada"] == Decimal("2")
    assert segunda["cantidadEjecutada"] == Decimal("2")

    posicion = obtener_posicion(
        escenario["portafolio"],
        escenario["instrumento"],
    )

    assert posicion["cantidad"].to_decimal() == Decimal("2")

    saldo = consultar_saldo(escenario["portafolio"])

    assert saldo["bloqueado"] == Decimal("800.00")
