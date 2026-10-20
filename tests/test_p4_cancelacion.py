"""Pruebas unitarias de cancelación, vencimiento y compensación."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.problemas.p4_cancelacion import cancelar_orden, expirar_orden, expirar_ordenes


FECHA = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)


@pytest.fixture
def contexto():
    return {
        "orden": uuid4(), "portafolio": uuid4(), "cierre": uuid4(),
    }


@pytest.fixture
def repositorios(contexto):
    modulo = "app.problemas.p4_cancelacion"
    with (
        patch(f"{modulo}.obtener_orden") as obtener,
        patch(f"{modulo}.obtener_saga", return_value=None) as saga,
        patch(f"{modulo}.crear_saga") as crear,
        patch(f"{modulo}.registrar_paso_saga") as paso,
        patch(f"{modulo}.cambiar_estado_saga") as estado,
        patch(f"{modulo}.tomar_orden_para_cierre") as tomar,
        patch(f"{modulo}.liberar_reserva_orden", return_value=Decimal("600")) as liberar,
        patch(f"{modulo}.revertir_liberacion_orden") as revertir,
        patch(f"{modulo}.finalizar_cierre_orden") as finalizar,
    ):
        orden = {
            "_id": str(contexto["orden"]),
            "idPortafolio": str(contexto["portafolio"]),
            "tipo": "COMPRA", "estado": "PENDIENTE", "fechaExpiracion": FECHA,
        }
        obtener.return_value = orden
        tomar.return_value = {
            **orden, "estado": "EN_CANCELACION", "idCierre": str(contexto["cierre"]),
        }
        finalizar.return_value = {**orden, "estado": "CANCELADA"}
        yield {
            "obtener": obtener, "saga": saga, "crear": crear, "paso": paso,
            "estado": estado, "tomar": tomar, "liberar": liberar,
            "revertir": revertir, "finalizar": finalizar,
        }


def ejecutar(contexto, **opciones):
    return cancelar_orden(contexto["orden"], contexto["cierre"], **opciones)


def test_cancelacion_exitosa(contexto, repositorios):
    resultado = ejecutar(contexto)
    assert resultado["estado"] == "CANCELADA"
    repositorios["liberar"].assert_called_once_with(
        contexto["portafolio"], contexto["orden"], contexto["cierre"]
    )
    repositorios["finalizar"].assert_called_once_with(
        contexto["orden"], contexto["cierre"], "CANCELADA", "COMPLETADA"
    )
    repositorios["revertir"].assert_not_called()


@pytest.mark.parametrize("opciones", [
    {"id_orden": "incorrecto"}, {"id_cancelacion": "incorrecto"},
    {"forzar_falla": "DESCONOCIDA"},
])
def test_argumentos_invalidos(contexto, repositorios, opciones):
    argumentos = {"id_orden": contexto["orden"], **opciones}
    with pytest.raises(ValueError):
        cancelar_orden(**argumentos)
    repositorios["crear"].assert_not_called()
    repositorios["liberar"].assert_not_called()


@pytest.mark.parametrize("estado", ["EJECUTADA", "VENCIDA", "RECHAZADA", "EN_EJECUCION"])
def test_rechaza_estado_no_cancelable(contexto, repositorios, estado):
    repositorios["obtener"].return_value["estado"] = estado
    with pytest.raises(ValueError, match="no admite"):
        ejecutar(contexto)
    repositorios["liberar"].assert_not_called()


def test_rechaza_orden_inexistente(contexto, repositorios):
    repositorios["obtener"].return_value = None
    with pytest.raises(ValueError, match="no existe"):
        ejecutar(contexto)
    repositorios["crear"].assert_not_called()


def test_repetir_cancelacion_no_libera_dos_veces(contexto, repositorios):
    repositorios["obtener"].return_value["estado"] = "CANCELADA"
    assert ejecutar(contexto)["estado"] == "CANCELADA"
    repositorios["crear"].assert_not_called()
    repositorios["liberar"].assert_not_called()


def test_no_reutiliza_identificador_de_otra_orden(contexto, repositorios):
    repositorios["saga"].return_value = {
        "tipo": "CANCELAR_ORDEN", "estado": "COMPLETADA",
        "datos": {"idOrden": str(uuid4())},
    }
    with pytest.raises(ValueError, match="datos diferentes"):
        ejecutar(contexto)
    repositorios["liberar"].assert_not_called()


@pytest.mark.parametrize("vencimiento", [None, FECHA + timedelta(seconds=1)])
def test_no_expira_antes_de_tiempo(contexto, repositorios, vencimiento):
    repositorios["obtener"].return_value["fechaExpiracion"] = vencimiento
    with pytest.raises(ValueError):
        expirar_orden(contexto["orden"], FECHA)
    repositorios["liberar"].assert_not_called()


@pytest.mark.parametrize("fecha", ["2026-10-20", datetime(2026, 10, 20)])
def test_expiracion_rechaza_fecha_invalida(contexto, repositorios, fecha):
    with pytest.raises(ValueError, match="zona horaria"):
        expirar_orden(contexto["orden"], fecha)
    repositorios["crear"].assert_not_called()


def test_expira_en_el_instante_de_vencimiento(contexto, repositorios):
    fecha_local = FECHA.astimezone(timezone(timedelta(hours=-3)))
    expirar_orden(contexto["orden"], fecha_local, contexto["cierre"])
    repositorios["tomar"].assert_called_once_with(
        contexto["orden"], contexto["cierre"], "PENDIENTE", FECHA
    )
    repositorios["finalizar"].assert_called_once_with(
        contexto["orden"], contexto["cierre"], "VENCIDA", "COMPLETADA"
    )


def test_ejecucion_en_curso_no_libera_fondos(contexto, repositorios):
    repositorios["tomar"].return_value = None
    with pytest.raises(ValueError, match="ejecución en curso"):
        ejecutar(contexto)
    repositorios["liberar"].assert_not_called()
    repositorios["revertir"].assert_not_called()
    repositorios["estado"].assert_called_with(contexto["cierre"], "FALLIDA")


@pytest.mark.parametrize("falla", ["ORDEN", "SALDO"])
def test_falla_compensa_antes_de_reabrir_orden(contexto, repositorios, falla):
    repositorios["obtener"].side_effect = [
        repositorios["obtener"].return_value,
        repositorios["tomar"].return_value,
    ]
    with pytest.raises(RuntimeError, match="Falla simulada"):
        ejecutar(contexto, forzar_falla=falla)
    repositorios["revertir"].assert_called_once()
    repositorios["finalizar"].assert_called_once_with(
        contexto["orden"], contexto["cierre"], "PENDIENTE", "COMPENSADA"
    )


def test_compensacion_fallida_no_reabre_orden(contexto, repositorios):
    repositorios["obtener"].side_effect = [
        repositorios["obtener"].return_value,
        repositorios["tomar"].return_value,
    ]
    repositorios["revertir"].side_effect = RuntimeError("PostgreSQL no disponible")
    with pytest.raises(RuntimeError, match="compensación incompleta"):
        ejecutar(contexto, forzar_falla="SALDO")
    repositorios["finalizar"].assert_not_called()
    repositorios["estado"].assert_called_with(contexto["cierre"], "REQUIERE_REVISION")


def test_respuesta_perdida_al_confirmar_no_rebloquea(contexto, repositorios):
    cerrada = {
        **repositorios["obtener"].return_value,
        "estado": "CANCELADA", "idCierre": str(contexto["cierre"]),
    }
    repositorios["obtener"].side_effect = [repositorios["obtener"].return_value, cerrada]
    repositorios["finalizar"].side_effect = RuntimeError("Respuesta perdida")
    assert ejecutar(contexto) == cerrada
    repositorios["revertir"].assert_not_called()


def test_lote_continua_si_una_orden_falla():
    primera, segunda = uuid4(), uuid4()
    modulo = "app.problemas.p4_cancelacion"
    with (
        patch(f"{modulo}.listar_ordenes_vencidas", return_value=[
            {"_id": str(primera)}, {"_id": str(segunda)},
        ]),
        patch(f"{modulo}.expirar_orden", side_effect=[
            RuntimeError("Ejecución en curso"), {"_id": str(segunda), "estado": "VENCIDA"},
        ]),
    ):
        resultado = expirar_ordenes(FECHA)
    assert resultado["vencidas"] == [{"_id": str(segunda), "estado": "VENCIDA"}]
    assert resultado["errores"][0]["idOrden"] == str(primera)
