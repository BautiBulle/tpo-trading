"""P5 con MongoDB temporal y claves Redis propias de cada prueba."""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app import config
from app.problemas.p5_valor_portafolio import calcular_valor_portafolio
from app.repos.mongo_repo import crear_portafolio, crear_instrumento, suspender_instrumento
from app.repos.posiciones_mongo import aplicar_compra, revertir_compra
from app.repos.precios_redis import set_precio


FECHA = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)


@pytest.fixture
def escenario():
    from unittest.mock import patch

    portafolio = uuid4()
    instrumentos = [uuid4(), uuid4()]
    simbolos = [f"P5-{identificador}" for identificador in instrumentos]

    crear_portafolio(portafolio, uuid4())

    for identificador, simbolo in zip(instrumentos, simbolos):
        crear_instrumento(identificador, simbolo, "Prueba P5", "TEST")

    try:
        with patch(
            "app.problemas.p5_valor_portafolio.consultar_precios",
            return_value=[],
        ):
            yield {
                "portafolio": portafolio,
                "instrumentos": instrumentos,
                "simbolos": simbolos,
            }
    finally:
        config.get_redis().delete(
            *(f"precio:{simbolo}" for simbolo in simbolos)
        )


def cotizar(simbolo, precio, fecha=FECHA):
    set_precio(simbolo, precio - Decimal("1"), precio + Decimal("1"), precio, fecha)


def test_valor_con_posiciones_del_p3_y_aislamiento_entre_portafolios(escenario):
    primero, segundo = escenario["instrumentos"]
    aplicar_compra(escenario["portafolio"], primero, Decimal("2.5"), Decimal("90"), uuid4())
    aplicar_compra(escenario["portafolio"], segundo, Decimal("3"), Decimal("15"), uuid4())
    # Una compra en otro portafolio no debe contarse en el consultado.
    otro = uuid4()
    crear_portafolio(otro, uuid4())
    aplicar_compra(otro, primero, Decimal("100"), Decimal("90"), uuid4())
    cotizar(escenario["simbolos"][0], Decimal("110"))
    cotizar(escenario["simbolos"][1], Decimal("20"))

    resultado = calcular_valor_portafolio(escenario["portafolio"])

    assert resultado["valorTotal"] == Decimal("335.00")
    assert len(resultado["posiciones"]) == 2
    assert {posicion["valorActual"] for posicion in resultado["posiciones"]} == {
        Decimal("275.00"), Decimal("60.00"),
    }


def test_nueva_cotizacion_cambia_el_valor_sin_modificar_datos(escenario):
    portafolio = escenario["portafolio"]
    simbolo = escenario["simbolos"][0]
    aplicar_compra(portafolio, escenario["instrumentos"][0], Decimal("2"), Decimal("100"), uuid4())
    cotizar(simbolo, Decimal("110"))
    assert calcular_valor_portafolio(portafolio)["valorTotal"] == Decimal("220")
    cotizar(simbolo, Decimal("120"), FECHA + timedelta(seconds=1))
    db = config.get_mongo_db()
    posiciones = list(db.posiciones.find({"idPortafolio": str(portafolio)}))
    documento = db.portafolios.find_one({"_id": str(portafolio)})
    precio = config.get_redis().hgetall(f"precio:{simbolo}")

    resultado = calcular_valor_portafolio(portafolio)

    assert resultado["valorTotal"] == Decimal("240")
    assert resultado["posiciones"][0]["fechaCotizacion"] == FECHA + timedelta(seconds=1)
    assert list(db.posiciones.find({"idPortafolio": str(portafolio)})) == posiciones
    assert db.portafolios.find_one({"_id": str(portafolio)}) == documento
    assert config.get_redis().hgetall(f"precio:{simbolo}") == precio


def test_compra_revertida_no_aporta_valor_ni_requiere_precio(escenario):
    ejecucion = uuid4()
    aplicar_compra(
        escenario["portafolio"], escenario["instrumentos"][0],
        Decimal("2"), Decimal("100"), ejecucion,
    )
    revertir_compra(ejecucion)
    resultado = calcular_valor_portafolio(escenario["portafolio"])
    assert resultado["valorTotal"] == Decimal("0")
    assert resultado["posiciones"] == []


def test_portafolio_sin_compras_vale_cero(escenario):
    resultado = calcular_valor_portafolio(escenario["portafolio"])
    assert resultado["valorTotal"] == Decimal("0")
    assert resultado["posiciones"] == []


def test_posicion_sin_cotizacion_informa_error(escenario):
    aplicar_compra(
        escenario["portafolio"], escenario["instrumentos"][0],
        Decimal("2"), Decimal("100"), uuid4(),
    )
    with pytest.raises(ValueError, match="No existe cotización vigente"):
        calcular_valor_portafolio(escenario["portafolio"])


def test_suspension_no_elimina_la_tenencia(escenario):
    instrumento = escenario["instrumentos"][0]
    aplicar_compra(escenario["portafolio"], instrumento, Decimal("2"), Decimal("100"), uuid4())
    cotizar(escenario["simbolos"][0], Decimal("110"))
    suspender_instrumento(instrumento)
    assert calcular_valor_portafolio(escenario["portafolio"])["valorTotal"] == Decimal("220")
