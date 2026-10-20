"""P4 contra bases reales temporales; habilitar con RUN_P4_INTEGRATION=1."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from app import config
from app.problemas.p2_colocar_orden import colocar_orden_compra
from app.problemas.p3_ejecucion import ejecutar_orden_compra
from app.problemas.p4_cancelacion import cancelar_orden, expirar_orden, expirar_ordenes
from app.problemas.p5_valor_portafolio import calcular_valor_portafolio
from app.repos.mongo_repo import (
    crear_usuario, crear_portafolio, crear_instrumento, crear_orden, obtener_orden,
    obtener_saga, reservar_ejecucion_orden, tomar_orden_para_cierre,
    finalizar_cierre_orden,
)
from app.repos.saldo_pg import (
    depositar, bloquear, consultar_saldo, liberar_reserva_orden,
    revertir_liberacion_orden, retirar,
)
from app.repos.posiciones_mongo import obtener_posicion
from app.repos.historial_cass import consultar_operaciones_usuario
from app.repos.precios_redis import set_precio


FECHA = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)


@pytest.fixture(scope="module", autouse=True)
def bases_temporales():
    if os.getenv("RUN_P4_INTEGRATION") != "1":
        pytest.skip("Habilitar con RUN_P4_INTEGRATION=1")

    # No se modifica el esquema ni los datos de las bases de trabajo.
    nombre = "tpo_p4_test_" + uuid4().hex[:12]
    raiz = Path(__file__).resolve().parents[1]
    pg = config.get_pg()
    mongo = config.get_mongo_db().client
    cass = config.get_cassandra()
    pg_creada = cass_creada = False
    conexiones_temporales = False
    cambios = pytest.MonkeyPatch()
    try:
        pg.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nombre)))
        pg_creada = True
        with psycopg.connect(
            host=config.PG_HOST, port=config.PG_PORT, user=config.PG_USER,
            password=config.PG_PASSWORD, dbname=nombre, autocommit=True,
        ) as temporal:
            temporal.execute((raiz / "init/postgres.sql").read_text(encoding="utf-8"))

        esquema = (raiz / "init/cassandra.cql").read_text(encoding="utf-8")
        for sentencia in esquema.replace("tpo_trading", nombre).split(";"):
            if sentencia.strip():
                cass.execute(sentencia)
                if "CREATE KEYSPACE" in sentencia:
                    cass_creada = True

        for atributo in ("PG_DB", "MONGO_DB", "CASSANDRA_KEYSPACE"):
            cambios.setattr(config, atributo, nombre)
        for atributo in ("_pg", "_mongo", "_cass"):
            cambios.setattr(config, atributo, None)
        conexiones_temporales = True

        from init.mongo_indexes import main as inicializar_mongo
        inicializar_mongo()
        yield
    finally:
        if conexiones_temporales:
            config.cerrar_todo()
        cambios.undo()
        try:
            mongo.drop_database(nombre)
        finally:
            try:
                if cass_creada:
                    cass.execute("DROP KEYSPACE " + nombre)
            finally:
                try:
                    if pg_creada:
                        pg.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(nombre)))
                finally:
                    config.cerrar_todo()


def nueva_orden(escenario, cantidad=Decimal("10"), precio=Decimal("100"), fecha=None):
    orden = uuid4()
    crear_orden(
        orden, escenario["portafolio"], escenario["instrumento"],
        "COMPRA", cantidad, precio, fecha_expiracion=fecha,
    )
    bloquear(
        escenario["portafolio"], (cantidad * precio).quantize(Decimal("0.01")),
        uuid4(), orden,
    )
    return orden


@pytest.fixture
def escenario():
    datos = {nombre: uuid4() for nombre in ("usuario", "portafolio", "instrumento")}
    crear_usuario(datos["usuario"], "Prueba P4", f"{datos['usuario']}@test.local")
    crear_portafolio(datos["portafolio"], datos["usuario"])
    crear_instrumento(datos["instrumento"], f"P4-{datos['instrumento']}", "Prueba", "TEST")
    depositar(datos["portafolio"], Decimal("10000.00"), uuid4())
    datos["orden"] = nueva_orden(datos)
    yield datos
    # Evita que el barrido de vencimientos encuentre órdenes de otro test.
    config.get_mongo_db().ordenes.delete_many({"idPortafolio": str(datos["portafolio"])})


def test_cancelacion_libera_toda_la_reserva(escenario):
    cierre = uuid4()
    resultado = cancelar_orden(escenario["orden"], cierre)
    assert resultado["estado"] == "CANCELADA"
    assert consultar_saldo(escenario["portafolio"]) == {
        "disponible": Decimal("10000.00"), "bloqueado": Decimal("0.00"),
    }
    saga = obtener_saga(cierre)
    assert saga["estado"] == "COMPLETADA"
    assert [paso["paso"] for paso in saga["pasos"]] == [
        "TOMAR_ORDEN", "LIBERAR_FONDOS", "CERRAR_ORDEN",
    ]


def test_flujo_completo_p2_p3_p4(escenario):
    simbolo = f"P4-{escenario['instrumento']}"
    try:
        set_precio(
            simbolo, Decimal("99"), Decimal("100"), Decimal("99.50"),
            datetime.now(timezone.utc),
        )
        id_orden = uuid4()
        colocar_orden_compra(
            escenario["portafolio"], escenario["instrumento"],
            Decimal("2"), Decimal("100.00"), id_orden,
        )
        ejecutar_orden_compra(id_orden, Decimal("1"))
        valor_ejecutado = calcular_valor_portafolio(escenario["portafolio"])
        assert valor_ejecutado["valorTotal"] == Decimal("99.50")
        cancelada = cancelar_orden(id_orden)
        assert cancelada["estado"] == "CANCELADA"
        assert cancelada["cantidadEjecutada"] == Decimal("1")
        assert calcular_valor_portafolio(escenario["portafolio"])["posiciones"] == (
            valor_ejecutado["posiciones"]
        )
        assert consultar_saldo(escenario["portafolio"]) == {
            "disponible": Decimal("8900.00"), "bloqueado": Decimal("1000.00"),
        }
    finally:
        config.get_redis().delete(f"precio:{simbolo}")


def test_cancelacion_parcial_conserva_posicion_e_historial(escenario):
    ejecutar_orden_compra(escenario["orden"], Decimal("4"))
    posicion = obtener_posicion(escenario["portafolio"], escenario["instrumento"])
    ahora = datetime.now(timezone.utc)
    historial = consultar_operaciones_usuario(
        escenario["usuario"], ahora - timedelta(days=1), ahora + timedelta(days=1)
    )
    resultado = cancelar_orden(escenario["orden"])
    assert resultado["cantidadEjecutada"] == Decimal("4")
    assert consultar_saldo(escenario["portafolio"]) == {
        "disponible": Decimal("9600.00"), "bloqueado": Decimal("0.00"),
    }
    assert obtener_posicion(escenario["portafolio"], escenario["instrumento"]) == posicion
    assert consultar_operaciones_usuario(
        escenario["usuario"], ahora - timedelta(days=1), ahora + timedelta(days=1)
    ) == historial


def test_libera_importe_real_aun_con_redondeos_y_otra_orden(escenario):
    otra = nueva_orden(escenario, Decimal("3"), Decimal("0.03"))
    ejecutar_orden_compra(otra, Decimal("1.5"))  # Consume 0.04 de los 0.09 reservados.
    antes = consultar_saldo(escenario["portafolio"])
    cancelar_orden(otra)
    despues = consultar_saldo(escenario["portafolio"])
    assert despues["disponible"] == antes["disponible"] + Decimal("0.05")
    assert despues["bloqueado"] == Decimal("1000.00")
    assert obtener_orden(escenario["orden"])["estado"] == "PENDIENTE"


def test_reintentos_no_duplican_liberacion(escenario):
    cierre = uuid4()
    primera = cancelar_orden(escenario["orden"], cierre)
    saldo = consultar_saldo(escenario["portafolio"])
    assert cancelar_orden(escenario["orden"], cierre) == primera
    assert cancelar_orden(escenario["orden"]) == primera
    assert consultar_saldo(escenario["portafolio"]) == saldo
    with config.get_pg().cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM movimiento_saldo WHERE id_orden = %s AND tipo = 'LIBERACION'",
            (escenario["orden"],),
        )
        assert cur.fetchone()[0] == 1


@pytest.mark.parametrize("falla", ["ORDEN", "SALDO"])
def test_rollback_restaura_orden_y_dinero(escenario, falla):
    cierre = uuid4()
    saldo = consultar_saldo(escenario["portafolio"])
    with pytest.raises(RuntimeError, match="Falla simulada"):
        cancelar_orden(escenario["orden"], cierre, forzar_falla=falla)
    assert consultar_saldo(escenario["portafolio"]) == saldo
    orden = obtener_orden(escenario["orden"])
    assert orden["estado"] == "PENDIENTE"
    assert "idCierre" not in orden
    assert obtener_saga(cierre)["estado"] == "COMPENSADA"
    with pytest.raises(RuntimeError, match="saga pendiente o fallida"):
        cancelar_orden(escenario["orden"], cierre)
    assert cancelar_orden(escenario["orden"])["estado"] == "CANCELADA"


def test_error_despues_de_liberar_tambien_compensa(escenario):
    original = liberar_reserva_orden

    def liberar_y_fallar(*argumentos):
        original(*argumentos)
        raise RuntimeError("Respuesta PostgreSQL perdida")

    saldo = consultar_saldo(escenario["portafolio"])
    with patch("app.problemas.p4_cancelacion.liberar_reserva_orden", side_effect=liberar_y_fallar):
        with pytest.raises(RuntimeError, match="Respuesta PostgreSQL perdida"):
            cancelar_orden(escenario["orden"])
    assert consultar_saldo(escenario["portafolio"]) == saldo
    assert obtener_orden(escenario["orden"])["estado"] == "PENDIENTE"


def test_compensacion_incompleta_mantiene_orden_tomada(escenario):
    cierre = uuid4()
    with patch(
        "app.problemas.p4_cancelacion.revertir_liberacion_orden",
        side_effect=RuntimeError("PostgreSQL no disponible"),
    ):
        with pytest.raises(RuntimeError, match="compensación incompleta"):
            cancelar_orden(escenario["orden"], cierre, forzar_falla="SALDO")
    assert obtener_orden(escenario["orden"])["estado"] == "EN_CANCELACION"
    assert obtener_saga(cierre)["estado"] == "REQUIERE_REVISION"
    with pytest.raises(ValueError, match="no admite"):
        reservar_ejecucion_orden(escenario["orden"], uuid4(), Decimal("1"))


def test_no_reabre_si_otro_movimiento_gasto_el_dinero_liberado(escenario):
    def liberar_y_retirar(*argumentos):
        importe = liberar_reserva_orden(*argumentos)
        saldo = consultar_saldo(escenario["portafolio"])
        retirar(escenario["portafolio"], saldo["disponible"], uuid4())
        return importe

    cierre = uuid4()
    with patch(
        "app.problemas.p4_cancelacion.liberar_reserva_orden", side_effect=liberar_y_retirar
    ):
        with pytest.raises(RuntimeError, match="compensación incompleta"):
            cancelar_orden(escenario["orden"], cierre, forzar_falla="SALDO")
    assert obtener_orden(escenario["orden"])["estado"] == "EN_CANCELACION"
    assert obtener_saga(cierre)["estado"] == "REQUIERE_REVISION"
    assert consultar_saldo(escenario["portafolio"])["disponible"] == Decimal("0")


def test_confirmacion_real_con_respuesta_perdida_no_compensa(escenario):
    def confirmar_y_fallar(*argumentos):
        finalizar_cierre_orden(*argumentos)
        raise RuntimeError("Respuesta MongoDB perdida")

    cierre = uuid4()
    with patch(
        "app.problemas.p4_cancelacion.finalizar_cierre_orden", side_effect=confirmar_y_fallar
    ):
        resultado = cancelar_orden(escenario["orden"], cierre)
    assert resultado["estado"] == "CANCELADA"
    assert obtener_saga(cierre)["estado"] == "COMPLETADA"
    assert consultar_saldo(escenario["portafolio"])["bloqueado"] == Decimal("0")


def test_no_cancela_una_ejecucion_en_curso(escenario):
    reservar_ejecucion_orden(escenario["orden"], uuid4(), Decimal("3"))
    saldo = consultar_saldo(escenario["portafolio"])
    with pytest.raises(ValueError, match="ejecución en curso"):
        cancelar_orden(escenario["orden"])
    assert consultar_saldo(escenario["portafolio"]) == saldo
    assert obtener_orden(escenario["orden"])["estado"] == "PENDIENTE"


def test_dos_cierres_solo_pueden_tomar_la_orden_una_vez(escenario):
    def tomar(identificador):
        return tomar_orden_para_cierre(escenario["orden"], identificador, "PENDIENTE")
    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        resultados = list(ejecutor.map(tomar, [uuid4(), uuid4()]))
    assert sum(resultado is not None for resultado in resultados) == 1
    with pytest.raises(ValueError, match="no admite"):
        reservar_ejecucion_orden(escenario["orden"], uuid4(), Decimal("1"))


def test_no_cancela_una_orden_totalmente_ejecutada(escenario):
    ejecutar_orden_compra(escenario["orden"], Decimal("10"))
    saldo = consultar_saldo(escenario["portafolio"])
    with pytest.raises(ValueError, match="no admite"):
        cancelar_orden(escenario["orden"])
    assert consultar_saldo(escenario["portafolio"]) == saldo


def test_expiracion_parcial_y_reintento(escenario):
    orden = nueva_orden(escenario, fecha=FECHA)
    ejecutar_orden_compra(orden, Decimal("2"))
    with pytest.raises(ValueError, match="todavía no venció"):
        expirar_orden(orden, FECHA - timedelta(seconds=1))
    resultado = expirar_orden(orden, FECHA)
    assert resultado["estado"] == "VENCIDA"
    assert resultado["cantidadEjecutada"] == Decimal("2")
    saldo = consultar_saldo(escenario["portafolio"])
    assert saldo["disponible"] == Decimal("8800.00")
    assert saldo["bloqueado"] == Decimal("1000.00")
    assert expirar_orden(orden, FECHA) == resultado
    assert consultar_saldo(escenario["portafolio"]) == saldo


def test_liberacion_y_compensacion_son_idempotentes(escenario):
    cierre = uuid4()
    argumentos = (escenario["portafolio"], escenario["orden"], cierre)
    saldo = consultar_saldo(escenario["portafolio"])
    assert liberar_reserva_orden(*argumentos) == Decimal("1000.00")
    assert liberar_reserva_orden(*argumentos) == Decimal("1000.00")
    assert revertir_liberacion_orden(*argumentos) is True
    assert revertir_liberacion_orden(*argumentos) is False
    assert consultar_saldo(escenario["portafolio"]) == saldo


def test_lote_omite_futuras_y_sin_fecha_y_reporta_orden_ocupada(escenario):
    vencida = nueva_orden(escenario, fecha=FECHA)
    futura = nueva_orden(escenario, fecha=FECHA + timedelta(days=1))
    ocupada = nueva_orden(escenario, fecha=FECHA)
    reservar_ejecucion_orden(ocupada, uuid4(), Decimal("1"))
    resultado = expirar_ordenes(FECHA)
    assert [orden["_id"] for orden in resultado["vencidas"]] == [str(vencida)]
    assert [error["idOrden"] for error in resultado["errores"]] == [str(ocupada)]
    assert obtener_orden(futura)["estado"] == "PENDIENTE"
    assert obtener_orden(escenario["orden"])["estado"] == "PENDIENTE"
