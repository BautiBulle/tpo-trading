"""Pruebas unitarias del Problema 2: colocación de órdenes."""

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.problemas.p2_colocar_orden import colocar_orden_compra


@pytest.fixture
def contexto():
    portafolio = uuid4()
    instrumento = uuid4()
    orden = uuid4()

    return {
        "portafolio": portafolio,
        "instrumento": instrumento,
        "orden": orden,
        "cantidad": Decimal("2"),
        "precio": Decimal("100.00"),
    }


@pytest.fixture
def repositorios(contexto):
    modulo = "app.problemas.p2_colocar_orden"

    with (
        patch(f"{modulo}.obtener_orden") as obtener_orden,
        patch(f"{modulo}.obtener_portafolio") as obtener_portafolio,
        patch(f"{modulo}.obtener_instrumento") as obtener_instrumento,
        patch(f"{modulo}.get_precio") as get_precio,
        patch(f"{modulo}.crear_saga") as crear_saga,
        patch(f"{modulo}.bloquear") as bloquear,
        patch(f"{modulo}.registrar_paso_saga") as registrar_paso,
        patch(f"{modulo}.crear_orden") as crear_orden,
        patch(f"{modulo}.cambiar_estado_saga") as cambiar_estado,
        patch(f"{modulo}.liberar") as liberar,
    ):
        obtener_orden.side_effect = [
            None,
            {
                "_id": str(contexto["orden"]),
                "estado": "PENDIENTE",
            },
        ]
        obtener_portafolio.return_value = {
            "_id": str(contexto["portafolio"])
        }
        obtener_instrumento.return_value = {
            "_id": str(contexto["instrumento"]),
            "estado": "ACTIVO",
            "simbolo": "ACT001",
        }
        get_precio.return_value = {
            "compra": Decimal("99.00"),
            "venta": Decimal("100.00"),
            "ultimo": Decimal("99.50"),
        }

        yield {
            "obtener_orden": obtener_orden,
            "obtener_portafolio": obtener_portafolio,
            "obtener_instrumento": obtener_instrumento,
            "get_precio": get_precio,
            "crear_saga": crear_saga,
            "bloquear": bloquear,
            "registrar_paso": registrar_paso,
            "crear_orden": crear_orden,
            "cambiar_estado": cambiar_estado,
            "liberar": liberar,
        }


def ejecutar(contexto):
    return colocar_orden_compra(
        contexto["portafolio"],
        contexto["instrumento"],
        contexto["cantidad"],
        contexto["precio"],
        contexto["orden"],
    )


def test_compra_exitosa(contexto, repositorios):
    resultado = ejecutar(contexto)

    assert resultado["estado"] == "PENDIENTE"

    repositorios["bloquear"].assert_called_once()
    assert repositorios["bloquear"].call_args.args[1] == Decimal("200.00")

    repositorios["crear_orden"].assert_called_once()
    repositorios["liberar"].assert_not_called()


def test_saldo_insuficiente(contexto, repositorios):
    repositorios["bloquear"].side_effect = ValueError(
        "Saldo disponible insuficiente"
    )

    with pytest.raises(ValueError, match="Saldo disponible insuficiente"):
        ejecutar(contexto)

    repositorios["crear_orden"].assert_not_called()
    repositorios["liberar"].assert_not_called()


def test_instrumento_suspendido(contexto, repositorios):
    repositorios["obtener_instrumento"].return_value["estado"] = "SUSPENDIDO"

    with pytest.raises(ValueError, match="suspendido"):
        ejecutar(contexto)

    repositorios["bloquear"].assert_not_called()


def test_precio_supera_limite(contexto, repositorios):
    repositorios["get_precio"].return_value["venta"] = Decimal("110.00")

    with pytest.raises(ValueError, match="precio de venta"):
        ejecutar(contexto)

    repositorios["bloquear"].assert_not_called()


def test_compensar_si_falla_creacion_orden(contexto, repositorios):
    repositorios["crear_orden"].side_effect = RuntimeError(
        "Error MongoDB"
    )

    repositorios["obtener_orden"].side_effect = [None, None]

    with pytest.raises(RuntimeError, match="Error MongoDB"):
        ejecutar(contexto)

    repositorios["bloquear"].assert_called_once()
    repositorios["liberar"].assert_called_once()

    estados = [
        llamada.args[1]
        for llamada in repositorios["cambiar_estado"].call_args_list
    ]
    assert "COMPENSADA" in estados


def test_reintento_orden_existente(contexto, repositorios):
    repositorios["obtener_orden"].side_effect = None
    repositorios["obtener_orden"].return_value = {
        "_id": str(contexto["orden"]),
        "idPortafolio": str(contexto["portafolio"]),
        "idInstrumento": str(contexto["instrumento"]),
        "tipo": "COMPRA",
        "cantidad": contexto["cantidad"],
        "precioLimite": contexto["precio"],
        "estado": "PENDIENTE",
    }

    resultado = ejecutar(contexto)

    assert resultado["estado"] == "PENDIENTE"
    repositorios["bloquear"].assert_not_called()
    repositorios["crear_orden"].assert_not_called()


def test_falla_forzada_al_registrar_orden_libera_saldo(contexto, repositorios):
    repositorios["obtener_orden"].side_effect = [None, None]

    with pytest.raises(RuntimeError, match="Falla simulada"):
        colocar_orden_compra(
            contexto["portafolio"],
            contexto["instrumento"],
            contexto["cantidad"],
            contexto["precio"],
            contexto["orden"],
            forzar_falla="ORDEN",
        )

    repositorios["bloquear"].assert_called_once()
    repositorios["crear_orden"].assert_not_called()
    repositorios["liberar"].assert_called_once()
    assert repositorios["liberar"].call_args.args[1] == Decimal("200.00")

    estados = [
        llamada.args[1]
        for llamada in repositorios["cambiar_estado"].call_args_list
    ]
    assert estados == ["COMPENSADA"]


def test_falla_desconocida(contexto, repositorios):
    with pytest.raises(ValueError, match="Escenario de falla"):
        colocar_orden_compra(
            contexto["portafolio"],
            contexto["instrumento"],
            contexto["cantidad"],
            contexto["precio"],
            contexto["orden"],
            forzar_falla="OTRA",
        )

    repositorios["bloquear"].assert_not_called()


def test_vence_al_cierre_del_mercado_por_defecto(contexto, repositorios):
    from datetime import datetime, timezone

    from app.constantes import HORA_CIERRE_MERCADO_UTC

    ejecutar(contexto)

    vencimiento = repositorios["crear_orden"].call_args.args[6]
    assert vencimiento > datetime.now(timezone.utc)
    assert vencimiento.hour == HORA_CIERRE_MERCADO_UTC
    assert vencimiento.minute == 0


def test_vencimiento_en_el_pasado_se_rechaza(contexto, repositorios):
    from datetime import datetime, timedelta, timezone

    with pytest.raises(ValueError, match="ya pasó"):
        colocar_orden_compra(
            contexto["portafolio"],
            contexto["instrumento"],
            contexto["cantidad"],
            contexto["precio"],
            contexto["orden"],
            fecha_expiracion=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

    repositorios["bloquear"].assert_not_called()


def test_cierre_de_mercado():
    from datetime import datetime, timezone

    from app.constantes import cierre_de_mercado

    antes = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)
    despues = datetime(2026, 10, 21, 21, 0, tzinfo=timezone.utc)
    assert cierre_de_mercado(antes) == datetime(2026, 10, 21, 20, tzinfo=timezone.utc)
    assert cierre_de_mercado(despues) == datetime(2026, 10, 22, 20, tzinfo=timezone.utc)
