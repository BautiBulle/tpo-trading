"""Pruebas del historial y la ganancia realizada de los últimos doce meses."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.problemas.p6_historial import (
    consultar_historial, calcular_rendimiento_12_meses,
)


HASTA = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
DESDE = HASTA.replace(year=2025)
USUARIO = uuid4()
INSTRUMENTO = uuid4()


def operacion(tipo, cantidad, precio, fecha=DESDE, simbolo="ACT001"):
    return {
        "id_operacion": uuid4(), "id_usuario": USUARIO,
        "id_instrumento": simbolo, "fecha_hora": fecha, "tipo": tipo,
        "cantidad": Decimal(cantidad), "precio": Decimal(precio),
        "importe": Decimal(cantidad) * Decimal(precio),
    }


@pytest.fixture
def repositorios():
    modulo = "app.problemas.p6_historial"
    with (
        patch(f"{modulo}.obtener_usuario") as usuario,
        patch(f"{modulo}.obtener_instrumento") as instrumento,
        patch(f"{modulo}.consultar_operaciones_usuario") as historial,
    ):
        usuario.return_value = {
            "_id": str(USUARIO),
            "fechaCreacion": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }
        instrumento.return_value = {
            "_id": str(INSTRUMENTO), "simbolo": "ACT001", "estado": "SUSPENDIDO",
        }
        historial.return_value = []
        yield {"usuario": usuario, "instrumento": instrumento, "historial": historial}


def test_historial_convierte_simbolo_y_fechas_sin_modificar_registros(repositorios):
    registro = operacion("COMPRA", "2.5", "100", DESDE.replace(tzinfo=None))
    repositorios["historial"].return_value = [registro]
    argentina = timezone(timedelta(hours=-3))
    resultado = consultar_historial(
        USUARIO, DESDE.astimezone(argentina), HASTA.astimezone(argentina), INSTRUMENTO,
    )
    repositorios["historial"].assert_called_once_with(USUARIO, DESDE, HASTA, "ACT001")
    assert resultado == [{
        "idOperacion": str(registro["id_operacion"]), "idUsuario": str(USUARIO),
        "simbolo": "ACT001", "fechaHora": DESDE, "tipo": "COMPRA",
        "cantidad": Decimal("2.5"), "precio": Decimal("100"),
        "importe": Decimal("250"),
    }]
    assert registro["fecha_hora"].tzinfo is None


def test_historial_sin_filtro_ordena_cronologicamente(repositorios):
    repositorios["historial"].return_value = [
        operacion("COMPRA", "1", "200", DESDE + timedelta(days=1), "ACT002"),
        operacion("COMPRA", "1", "100"),
    ]
    resultado = consultar_historial(USUARIO, DESDE, HASTA)
    assert [fila["simbolo"] for fila in resultado] == ["ACT001", "ACT002"]
    repositorios["instrumento"].assert_not_called()
    repositorios["historial"].assert_called_once_with(USUARIO, DESDE, HASTA, None)


@pytest.mark.parametrize("desde,hasta", [
    (DESDE.replace(tzinfo=None), HASTA), (DESDE, HASTA.replace(tzinfo=None)),
    ("2025-10-20", HASTA), (DESDE, DESDE), (HASTA, DESDE),
])
def test_historial_rechaza_intervalos_invalidos(repositorios, desde, hasta):
    with pytest.raises(ValueError):
        consultar_historial(USUARIO, desde, hasta)
    repositorios["historial"].assert_not_called()


@pytest.mark.parametrize("usuario,instrumento", [("incorrecto", None), (USUARIO, "ACT001")])
def test_rechaza_identificadores_invalidos(repositorios, usuario, instrumento):
    with pytest.raises(ValueError, match="UUID"):
        consultar_historial(usuario, DESDE, HASTA, instrumento)
    repositorios["historial"].assert_not_called()


@pytest.mark.parametrize("entidad", ["usuario", "instrumento"])
def test_rechaza_entidad_inexistente(repositorios, entidad):
    repositorios[entidad].return_value = None
    with pytest.raises(ValueError, match="no existe"):
        calcular_rendimiento_12_meses(USUARIO, HASTA, INSTRUMENTO)
    repositorios["historial"].assert_not_called()


def test_compras_y_ventas_anteriores_reconstruyen_costo(repositorios):
    repositorios["historial"].return_value = [
        operacion("COMPRA", "10", "100", DESDE - timedelta(days=100)),
        operacion("VENTA", "5", "140", DESDE - timedelta(days=50)),
        operacion("COMPRA", "5", "200", DESDE),
        operacion("VENTA", "2", "180", DESDE + timedelta(days=1)),
    ]
    resultado = calcular_rendimiento_12_meses(USUARIO, HASTA)
    assert resultado["desde"] == DESDE
    assert resultado["hasta"] == HASTA
    assert resultado["cantidadOperaciones"] == 2
    assert resultado["importeCompras"] == Decimal("1000")
    assert resultado["importeVentas"] == Decimal("360")
    assert resultado["costoVendido"] == Decimal("300")
    assert resultado["gananciaRealizada"] == Decimal("60")
    assert resultado["rendimientoPorcentual"] == Decimal("20")
    repositorios["historial"].assert_called_once_with(
        USUARIO, repositorios["usuario"].return_value["fechaCreacion"], HASTA, None,
    )


def test_liquidacion_total_no_deja_residuos_de_costo(repositorios):
    repositorios["historial"].return_value = [
        operacion(tipo, cantidad, precio, DESDE + timedelta(days=dia))
        for dia, (tipo, cantidad, precio) in enumerate([
            ("COMPRA", "1", "1"), ("COMPRA", "2", "2"),
            ("VENTA", "1", "3"), ("VENTA", "2", "3"),
            ("COMPRA", "1", "10"), ("VENTA", "1", "12"),
        ])
    ]
    resultado = calcular_rendimiento_12_meses(USUARIO, HASTA)
    assert resultado["costoVendido"] == Decimal("15")
    assert resultado["gananciaRealizada"] == Decimal("6")
    assert resultado["rendimientoPorcentual"] == Decimal("40")


def test_total_pondera_costos_en_lugar_de_promediar_porcentajes(repositorios):
    repositorios["historial"].return_value = [
        operacion("COMPRA", "1", "100"),
        operacion("COMPRA", "1", "900", simbolo="ACT002"),
        operacion("VENTA", "1", "200", DESDE + timedelta(days=1)),
        operacion("VENTA", "1", "810", DESDE + timedelta(days=1), "ACT002"),
    ]
    resultado = calcular_rendimiento_12_meses(USUARIO, HASTA)
    assert resultado["gananciaRealizada"] == Decimal("10")
    assert resultado["rendimientoPorcentual"] == Decimal("1")
    assert [fila["rendimientoPorcentual"] for fila in resultado["instrumentos"]] == [
        Decimal("100"), Decimal("-10"),
    ]


@pytest.mark.parametrize("con_compras", [False, True])
def test_sin_ventas_ganancia_cero_y_porcentaje_no_aplicable(repositorios, con_compras):
    if con_compras:
        repositorios["historial"].return_value = [operacion("COMPRA", "2", "100")]
    resultado = calcular_rendimiento_12_meses(USUARIO, HASTA)
    assert resultado["gananciaRealizada"] == Decimal("0")
    assert resultado["rendimientoPorcentual"] is None
    assert resultado["costoVendido"] == Decimal("0")


def test_ventas_anteriores_no_aportan_rendimiento(repositorios):
    repositorios["historial"].return_value = [
        operacion("COMPRA", "1", "100", DESDE - timedelta(days=2)),
        operacion("VENTA", "1", "120", DESDE - timedelta(days=1)),
    ]
    resultado = calcular_rendimiento_12_meses(USUARIO, HASTA)
    assert resultado["cantidadOperaciones"] == 0
    assert resultado["gananciaRealizada"] == Decimal("0")
    assert resultado["instrumentos"] == []


def test_rendimiento_permite_filtrar_instrumento_suspendido(repositorios):
    resultado = calcular_rendimiento_12_meses(USUARIO, HASTA, INSTRUMENTO)
    assert resultado["idInstrumento"] == str(INSTRUMENTO)
    assert repositorios["historial"].call_args.args[-1] == "ACT001"


def test_29_febrero_retrocede_un_anio_calendario(repositorios):
    repositorios["usuario"].return_value["fechaCreacion"] = datetime(2020, 1, 1, tzinfo=timezone.utc)
    fecha = datetime(2024, 2, 29, 12, tzinfo=timezone.utc)
    resultado = calcular_rendimiento_12_meses(USUARIO, fecha)
    assert resultado["desde"] == datetime(2023, 2, 28, 12, tzinfo=timezone.utc)


def test_antes_del_alta_no_consulta_cassandra(repositorios):
    fecha = datetime(2023, 1, 1, tzinfo=timezone.utc)
    assert calcular_rendimiento_12_meses(USUARIO, fecha)["cantidadOperaciones"] == 0
    repositorios["historial"].assert_not_called()


@pytest.mark.parametrize("fecha", [HASTA.replace(tzinfo=None), "2026-10-20", datetime(1, 1, 1, tzinfo=timezone.utc)])
def test_rendimiento_rechaza_fecha_invalida(repositorios, fecha):
    with pytest.raises(ValueError):
        calcular_rendimiento_12_meses(USUARIO, fecha)
    repositorios["historial"].assert_not_called()


def test_venta_sin_compras_suficientes_informa_historial_incompleto(repositorios):
    repositorios["historial"].return_value = [operacion("VENTA", "1", "100")]
    with pytest.raises(ValueError, match="Historial incompleto"):
        calcular_rendimiento_12_meses(USUARIO, HASTA)


def test_compra_y_venta_en_mismo_instante_no_inventa_orden(repositorios):
    repositorios["historial"].return_value = [
        operacion("COMPRA", "5", "100", DESDE - timedelta(days=1)),
        operacion("COMPRA", "2", "200"), operacion("VENTA", "1", "150"),
    ]
    with pytest.raises(ValueError, match="simultáneas"):
        calcular_rendimiento_12_meses(USUARIO, HASTA)


@pytest.mark.parametrize("campo,valor", [
    ("tipo", "DEPOSITO"), ("cantidad", Decimal("-1")),
    ("precio", Decimal("NaN")), ("cantidad", Decimal("Infinity")), ("precio", 100.0),
])
def test_datos_invalidos_no_producen_rendimiento(repositorios, campo, valor):
    registro = operacion("COMPRA", "1", "100")
    registro[campo] = valor
    repositorios["historial"].return_value = [registro]
    with pytest.raises(ValueError, match="inválid"):
        calcular_rendimiento_12_meses(USUARIO, HASTA)


def test_error_cassandra_no_devuelve_resultado_parcial(repositorios):
    repositorios["historial"].side_effect = RuntimeError("Cassandra no disponible")
    with pytest.raises(RuntimeError, match="Cassandra"):
        calcular_rendimiento_12_meses(USUARIO, HASTA)
