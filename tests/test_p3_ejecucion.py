"""Pruebas unitarias del Problema 3: ejecución al precio vigente."""

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4, uuid5

import pytest

from app.problemas.p3_ejecucion import ejecutar_orden_compra

MODULO = "app.problemas.p3_ejecucion"


@pytest.fixture
def contexto():
    return {
        "orden": uuid4(),
        "portafolio": uuid4(),
        "instrumento": uuid4(),
        "usuario": uuid4(),
    }


@pytest.fixture
def repos(contexto):
    nombres = (
        "obtener_orden", "obtener_portafolio", "obtener_instrumento",
        "crear_saga", "obtener_saga", "registrar_paso_saga",
        "cambiar_estado_saga", "reservar_ejecucion_orden",
        "confirmar_ejecucion_orden", "liberar_reserva_ejecucion",
        "aplicar_compra", "revertir_compra", "registrar_operacion",
        "revertir_operacion", "consumir", "revertir_consumo",
        "liberar_reserva_orden", "get_precio",
    )
    parches = {nombre: patch(f"{MODULO}.{nombre}") for nombre in nombres}
    mocks = {nombre: parche.start() for nombre, parche in parches.items()}

    orden = {
        "_id": str(contexto["orden"]),
        "idPortafolio": str(contexto["portafolio"]),
        "idInstrumento": str(contexto["instrumento"]),
        "tipo": "COMPRA",
        "cantidad": Decimal("10"),
        "precioLimite": Decimal("100.00"),
        "estado": "PENDIENTE",
    }
    mocks["obtener_orden"].side_effect = [
        orden, {**orden, "estado": "PARCIALMENTE_EJECUTADA"},
    ]
    mocks["obtener_portafolio"].return_value = {"idUsuario": str(contexto["usuario"])}
    mocks["obtener_instrumento"].return_value = {"simbolo": "ACT001", "estado": "ACTIVO"}
    mocks["obtener_saga"].return_value = None
    mocks["get_precio"].return_value = {
        "compra": Decimal("89.00"), "venta": Decimal("90.00"), "ultimo": Decimal("89.50"),
    }
    mocks["orden"] = orden
    yield mocks
    patch.stopall()


def test_ejecuta_al_precio_vigente_de_venta(contexto, repos):
    ejecutar_orden_compra(contexto["orden"], Decimal("4"))

    # Se paga el precio vigente (90), no el límite (100).
    assert repos["consumir"].call_args.args[1] == Decimal("360.00")
    assert repos["aplicar_compra"].call_args.args[3] == Decimal("90.00")
    assert repos["registrar_operacion"].call_args.args[6] == Decimal("90.00")

    datos = repos["crear_saga"].call_args.args[2]
    assert datos["precioVigente"] == Decimal("90.00")
    assert datos["precioLimite"] == Decimal("100.00")

    # Ejecución parcial: el resto sigue reservado.
    repos["liberar_reserva_orden"].assert_not_called()
    assert repos["cambiar_estado_saga"].call_args.args[1] == "COMPLETADA"


def test_precio_vigente_mayor_al_limite_no_ejecuta(contexto, repos):
    repos["get_precio"].return_value["venta"] = Decimal("101.00")

    with pytest.raises(ValueError, match="supera el precio límite"):
        ejecutar_orden_compra(contexto["orden"], Decimal("4"))

    repos["crear_saga"].assert_not_called()
    repos["consumir"].assert_not_called()


def test_sin_cotizacion_no_ejecuta(contexto, repos):
    repos["get_precio"].return_value = None

    with pytest.raises(ValueError, match="cotización vigente"):
        ejecutar_orden_compra(contexto["orden"], Decimal("4"))

    repos["crear_saga"].assert_not_called()


def test_al_completar_libera_el_sobrante(contexto, repos):
    primera = repos["orden"]
    repos["obtener_orden"].side_effect = [
        primera, {**primera, "estado": "EJECUTADA"}, {**primera, "estado": "EJECUTADA"},
    ]

    ejecutar_orden_compra(contexto["orden"], Decimal("10"))

    repos["liberar_reserva_orden"].assert_called_once_with(
        contexto["portafolio"], contexto["orden"],
        uuid5(contexto["orden"], "liberar-sobrante"),
    )
    pasos = [c.args[1] for c in repos["registrar_paso_saga"].call_args_list]
    assert pasos[-1] == "LIBERAR_SOBRANTE"
    assert repos["cambiar_estado_saga"].call_args.args[1] == "COMPLETADA"


def test_si_falla_liberar_sobrante_no_deshace_la_ejecucion(contexto, repos):
    primera = repos["orden"]
    repos["obtener_orden"].side_effect = [
        primera, {**primera, "estado": "EJECUTADA"}, {**primera, "estado": "EJECUTADA"},
    ]
    repos["liberar_reserva_orden"].side_effect = RuntimeError("PostgreSQL caído")

    resultado = ejecutar_orden_compra(contexto["orden"], Decimal("10"))

    assert resultado["estado"] == "EJECUTADA"
    repos["revertir_consumo"].assert_not_called()
    repos["revertir_compra"].assert_not_called()
    assert repos["cambiar_estado_saga"].call_args.args[1] == "LIBERACION_PENDIENTE"


def test_reintento_completa_la_liberacion_pendiente(contexto, repos):
    repos["obtener_saga"].return_value = {"estado": "LIBERACION_PENDIENTE"}
    primera = repos["orden"]
    repos["obtener_orden"].side_effect = [primera, {**primera, "estado": "EJECUTADA"}]

    ejecutar_orden_compra(contexto["orden"], Decimal("10"), id_ejecucion=uuid4())

    repos["liberar_reserva_orden"].assert_called_once()
    repos["consumir"].assert_not_called()
    assert repos["cambiar_estado_saga"].call_args.args[1] == "COMPLETADA"


@pytest.mark.parametrize("falla", ["POSICION", "HISTORIAL", "SALDO"])
def test_falla_forzada_compensa_todo(contexto, repos, falla):
    with pytest.raises(RuntimeError, match="Falla simulada"):
        ejecutar_orden_compra(contexto["orden"], Decimal("4"), forzar_falla=falla)

    repos["revertir_compra"].assert_called_once()
    repos["liberar_reserva_ejecucion"].assert_called_once()
    repos["confirmar_ejecucion_orden"].assert_not_called()
    repos["liberar_reserva_orden"].assert_not_called()
    if falla in ("HISTORIAL", "SALDO"):
        repos["revertir_operacion"].assert_called_once()
    if falla == "SALDO":
        repos["revertir_consumo"].assert_called_once()
    assert repos["cambiar_estado_saga"].call_args.args[1] == "COMPENSADA"
