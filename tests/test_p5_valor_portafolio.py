"""Pruebas unitarias del valor del portafolio y rendimiento diario."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.problemas.p5_valor_portafolio import calcular_valor_portafolio


FECHA = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)


@pytest.fixture
def contexto():
    return {"portafolio": uuid4(), "instrumento": uuid4()}


@pytest.fixture
def repositorios(contexto):
    modulo = "app.problemas.p5_valor_portafolio"

    with (
        patch(f"{modulo}.obtener_portafolio") as portafolio,
        patch(f"{modulo}.listar_posiciones_portafolio") as posiciones,
        patch(f"{modulo}.obtener_instrumento") as instrumento,
        patch(f"{modulo}.get_precio") as precio,
        patch(f"{modulo}.consultar_precios") as historico,
    ):
        portafolio.return_value = {
            "_id": str(contexto["portafolio"]),
            "posiciones": [],
        }

        posiciones.return_value = [{
            "idInstrumento": str(contexto["instrumento"]),
            "cantidad": Decimal("2.5"),
            "precioPromedio": Decimal("90.00"),
        }]

        instrumento.return_value = {
            "_id": str(contexto["instrumento"]),
            "simbolo": "ACT001",
            "estado": "ACTIVO",
        }

        precio.return_value = {
            "compra": Decimal("99"),
            "venta": Decimal("101"),
            "ultimo": Decimal("100"),
            "fechaHora": FECHA,
        }

        historico.return_value = [{
            "fecha_hora": FECHA,
            "precio_ultimo": Decimal("90"),
        }]

        yield {
            "portafolio": portafolio,
            "posiciones": posiciones,
            "instrumento": instrumento,
            "precio": precio,
            "historico": historico,
        }
      

def test_valor_usa_ultimo_precio_y_cantidad_fraccionaria(contexto, repositorios):
    resultado = calcular_valor_portafolio(contexto["portafolio"])

    assert resultado["idPortafolio"] == str(contexto["portafolio"])
    assert resultado["valorTotal"] == Decimal("250.00")
    assert resultado["posiciones"] == [{
        "idInstrumento": str(contexto["instrumento"]),
        "simbolo": "ACT001",
        "cantidad": Decimal("2.5"),
        "precioActual": Decimal("100"),
        "valorActual": Decimal("250.00"),
        "fechaCotizacion": FECHA,
        "precioReferenciaDiaria": Decimal("90"),
        "fechaReferenciaDiaria": FECHA,
        "rendimientoDiarioPorcentaje": Decimal("100") / Decimal("9"),
    }]
    assert resultado["fechaConsulta"].tzinfo == timezone.utc


def test_suma_varias_posiciones(contexto, repositorios):
    segunda = uuid4()

    repositorios["posiciones"].return_value.append({
        "idInstrumento": str(segunda),
        "cantidad": Decimal("3"),
        "precioPromedio": Decimal("10"),
    })

    repositorios["instrumento"].side_effect = [
        repositorios["instrumento"].return_value,
        {"_id": str(segunda), "simbolo": "ACT002", "estado": "ACTIVO"},
    ]

    repositorios["precio"].side_effect = [
        repositorios["precio"].return_value,
        {"ultimo": Decimal("20"), "fechaHora": FECHA},
    ]

    resultado = calcular_valor_portafolio(contexto["portafolio"])

    assert resultado["valorTotal"] == Decimal("310.00")
    assert len(resultado["posiciones"]) == 2


def test_no_redondea_antes_de_sumar(contexto, repositorios):
    repositorios["posiciones"].return_value[0]["cantidad"] = Decimal("0.0003")
    repositorios["precio"].return_value["ultimo"] = Decimal("0.1234")

    resultado = calcular_valor_portafolio(contexto["portafolio"])

    assert resultado["valorTotal"] == Decimal("0.00003702")


def test_portafolio_vacio_vale_cero(contexto, repositorios):
    repositorios["posiciones"].return_value = []

    resultado = calcular_valor_portafolio(contexto["portafolio"])

    assert resultado["valorTotal"] == Decimal("0.00")
    assert resultado["posiciones"] == []
    repositorios["precio"].assert_not_called()
    repositorios["historico"].assert_not_called()


def test_posicion_revertida_no_necesita_cotizacion(contexto, repositorios):
    repositorios["posiciones"].return_value[0]["cantidad"] = Decimal("0")

    assert calcular_valor_portafolio(contexto["portafolio"])["valorTotal"] == Decimal("0")

    repositorios["instrumento"].assert_not_called()
    repositorios["precio"].assert_not_called()
    repositorios["historico"].assert_not_called()


def test_instrumento_suspendido_conserva_su_valor(contexto, repositorios):
    repositorios["instrumento"].return_value["estado"] = "SUSPENDIDO"

    resultado = calcular_valor_portafolio(contexto["portafolio"])

    assert resultado["valorTotal"] == Decimal("250")


def test_cotizacion_cero_es_un_precio_valido(contexto, repositorios):
    repositorios["precio"].return_value["ultimo"] = Decimal("0")

    resultado = calcular_valor_portafolio(contexto["portafolio"])

    assert resultado["valorTotal"] == Decimal("0")
    assert len(resultado["posiciones"]) == 1
    assert resultado["posiciones"][0]["rendimientoDiarioPorcentaje"] == Decimal("-100")


def test_id_portafolio_invalido(repositorios):
    with pytest.raises(ValueError, match="UUID"):
        calcular_valor_portafolio("no-es-uuid")

    repositorios["portafolio"].assert_not_called()


def test_portafolio_inexistente(contexto, repositorios):
    repositorios["portafolio"].return_value = None

    with pytest.raises(ValueError, match="portafolio no existe"):
        calcular_valor_portafolio(contexto["portafolio"])

    repositorios["posiciones"].assert_not_called()


def test_instrumento_inexistente(contexto, repositorios):
    repositorios["instrumento"].return_value = None

    with pytest.raises(ValueError, match="instrumento.*no existe"):
        calcular_valor_portafolio(contexto["portafolio"])

    repositorios["precio"].assert_not_called()


def test_falta_cotizacion_no_devuelve_un_total_incompleto(contexto, repositorios):
    repositorios["precio"].return_value = None

    with pytest.raises(ValueError, match="cotización vigente para ACT001"):
        calcular_valor_portafolio(contexto["portafolio"])


@pytest.mark.parametrize(
    "cantidad",
    [Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), 1.0],
)
def test_rechaza_cantidad_invalida(contexto, repositorios, cantidad):
    repositorios["posiciones"].return_value[0]["cantidad"] = cantidad

    with pytest.raises(ValueError, match="cantidad inválida"):
        calcular_valor_portafolio(contexto["portafolio"])

    repositorios["precio"].assert_not_called()


@pytest.mark.parametrize(
    "precio",
    [Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), 1.0],
)
def test_rechaza_precio_invalido(contexto, repositorios, precio):
    repositorios["precio"].return_value["ultimo"] = precio

    with pytest.raises(ValueError, match="precio inválido"):
        calcular_valor_portafolio(contexto["portafolio"])


def test_error_redis_se_propaga(contexto, repositorios):
    repositorios["precio"].side_effect = ConnectionError("Redis no disponible")

    with pytest.raises(ConnectionError, match="Redis no disponible"):
        calcular_valor_portafolio(contexto["portafolio"])


def test_sin_historial_rendimiento_no_disponible(contexto, repositorios):
    repositorios["historico"].return_value = []

    resultado = calcular_valor_portafolio(contexto["portafolio"])

    posicion = resultado["posiciones"][0]

    assert posicion["precioReferenciaDiaria"] is None
    assert posicion["fechaReferenciaDiaria"] is None
    assert posicion["rendimientoDiarioPorcentaje"] is None
    assert resultado["valorTotal"] == Decimal("250.00")


def test_error_cassandra_se_propaga(contexto, repositorios):
    repositorios["historico"].side_effect = ConnectionError(
        "Cassandra no disponible"
    )

    with pytest.raises(ConnectionError, match="Cassandra no disponible"):
        calcular_valor_portafolio(contexto["portafolio"])
