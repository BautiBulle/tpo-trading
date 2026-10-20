"""P6 con MongoDB y Cassandra temporales; no modifica los datos de trabajo."""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from cassandra.cluster import Cluster

from app import config
from app.problemas.p6_historial import consultar_historial, calcular_rendimiento_12_meses
from app.repos.historial_cass import registrar_operacion, revertir_operacion
from app.repos.mongo_repo import crear_usuario, crear_instrumento, suspender_instrumento


HASTA = datetime(2026, 10, 20, 18, tzinfo=timezone.utc)
DESDE = HASTA.replace(year=2025)


@pytest.fixture(scope="module", autouse=True)
def bases_temporales():
    if os.getenv("RUN_P6_INTEGRATION") != "1":
        pytest.skip("Habilitar con RUN_P6_INTEGRATION=1")

    nombre = "tpo_p6_test_" + uuid4().hex[:12]
    mongo = config.get_mongo_db().client
    cluster = Cluster([config.CASSANDRA_HOST], port=config.CASSANDRA_PORT)
    sesion = None
    creada = False
    try:
        sesion = cluster.connect()
        raiz = Path(__file__).resolve().parents[1]
        esquema = (raiz / "init/cassandra.cql").read_text(encoding="utf-8")
        for sentencia in esquema.replace("tpo_trading", nombre).split(";"):
            if sentencia.strip():
                sesion.execute(sentencia)
                if "CREATE KEYSPACE" in sentencia:
                    creada = True

        with pytest.MonkeyPatch.context() as cambios:
            cambios.setattr(config, "MONGO_DB", nombre)
            cambios.setattr(config, "CASSANDRA_KEYSPACE", nombre)
            cambios.setattr(config, "_cass", sesion)
            yield
    finally:
        try:
            mongo.drop_database(nombre)
        finally:
            try:
                if creada:
                    sesion.execute("DROP KEYSPACE " + nombre)
            finally:
                cluster.shutdown()


@pytest.fixture
def escenario():
    usuario, instrumento = uuid4(), uuid4()
    simbolo = f"P6-{instrumento}"
    crear_usuario(usuario, "Prueba P6", f"{usuario}@test.local")
    # El historial de prueba comienza después del alta de la cuenta.
    config.get_mongo_db().usuarios.update_one(
        {"_id": str(usuario)},
        {"$set": {"fechaCreacion": datetime(2024, 1, 1, tzinfo=timezone.utc)}},
    )
    crear_instrumento(instrumento, simbolo, "Prueba P6", "TEST")
    return {"usuario": usuario, "instrumento": instrumento, "simbolo": simbolo}


def registrar(escenario, tipo, cantidad, precio, fecha):
    identificador = uuid4()
    registrar_operacion(
        identificador, escenario["usuario"], escenario["simbolo"], fecha,
        tipo, Decimal(cantidad), Decimal(precio),
    )
    return identificador


def test_historial_cruza_meses_y_anios_sin_mezclar_usuarios(escenario):
    diciembre = datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc)
    enero = diciembre + timedelta(minutes=1)
    primera = registrar(escenario, "COMPRA", "2", "100", diciembre)
    segunda = registrar(escenario, "VENTA", "1", "120", enero)
    registrar({**escenario, "usuario": uuid4()}, "COMPRA", "99", "100", enero)
    otro_instrumento = uuid4()
    otro_simbolo = f"P6-{otro_instrumento}"
    crear_instrumento(otro_instrumento, otro_simbolo, "Otro instrumento", "TEST")
    registrar({**escenario, "simbolo": otro_simbolo}, "COMPRA", "1", "50", enero)
    suspender_instrumento(escenario["instrumento"])

    argentina = timezone(timedelta(hours=-3))
    historial = consultar_historial(
        escenario["usuario"], diciembre.astimezone(argentina),
        (enero + timedelta(minutes=1)).astimezone(argentina), escenario["instrumento"],
    )
    assert [fila["idOperacion"] for fila in historial] == [str(primera), str(segunda)]
    assert all(fila["fechaHora"].tzinfo == timezone.utc for fila in historial)
    assert len(consultar_historial(escenario["usuario"], diciembre, enero)) == 1
    assert len(consultar_historial(escenario["usuario"], diciembre, HASTA)) == 3


def test_rendimiento_incluye_inicio_excluye_fin_y_usa_costos_anteriores(escenario):
    registrar(escenario, "COMPRA", "10", "100", DESDE - timedelta(days=400))
    registrar(escenario, "VENTA", "5", "140", DESDE - timedelta(days=30))
    registrar(escenario, "COMPRA", "5", "200", DESDE)
    registrar(escenario, "VENTA", "2", "180", DESDE + timedelta(days=20))
    registrar(escenario, "VENTA", "1", "900", HASTA)
    resultado = calcular_rendimiento_12_meses(escenario["usuario"], HASTA)
    assert resultado["cantidadOperaciones"] == 2
    assert resultado["importeCompras"] == Decimal("1000")
    assert resultado["importeVentas"] == Decimal("360")
    assert resultado["costoVendido"] == Decimal("300")
    assert resultado["gananciaRealizada"] == Decimal("60")
    assert resultado["rendimientoPorcentual"] == Decimal("20")


def test_consultas_no_escriben_en_las_bases(escenario):
    registrar(escenario, "COMPRA", "1", "100", DESDE)
    registrar(escenario, "VENTA", "1", "80", DESDE + timedelta(days=1))
    db = config.get_mongo_db()
    sesion = config.get_cassandra()
    usuarios = list(db.usuarios.find())
    instrumentos = list(db.instrumentos.find())
    por_usuario = list(sesion.execute("SELECT * FROM operaciones_por_usuario"))
    por_instrumento = list(sesion.execute("SELECT * FROM operaciones_por_instrumento"))

    consultar_historial(escenario["usuario"], DESDE, HASTA)
    resultado = calcular_rendimiento_12_meses(
        escenario["usuario"], HASTA, escenario["instrumento"],
    )
    assert resultado["rendimientoPorcentual"] == Decimal("-20")
    assert list(db.usuarios.find()) == usuarios
    assert list(db.instrumentos.find()) == instrumentos
    assert list(sesion.execute("SELECT * FROM operaciones_por_usuario")) == por_usuario
    assert list(sesion.execute("SELECT * FROM operaciones_por_instrumento")) == por_instrumento


def test_compensacion_del_p3_elimina_operacion_del_historial(escenario):
    identificador = registrar(escenario, "COMPRA", "3", "100", DESDE)
    assert len(consultar_historial(escenario["usuario"], DESDE, HASTA)) == 1
    revertir_operacion(identificador, escenario["usuario"], escenario["simbolo"], DESDE)
    assert consultar_historial(escenario["usuario"], DESDE, HASTA) == []
    resultado = calcular_rendimiento_12_meses(escenario["usuario"], HASTA)
    assert resultado["cantidadOperaciones"] == 0
    assert resultado["gananciaRealizada"] == Decimal("0")
    assert resultado["rendimientoPorcentual"] is None


def test_venta_sin_historial_de_compras_no_devuelve_ganancia_inventada(escenario):
    registrar(escenario, "VENTA", "1", "100", DESDE)
    with pytest.raises(ValueError, match="Historial incompleto"):
        calcular_rendimiento_12_meses(escenario["usuario"], HASTA)


def test_usuario_sin_operaciones(escenario):
    assert consultar_historial(escenario["usuario"], DESDE, HASTA) == []
    resultado = calcular_rendimiento_12_meses(escenario["usuario"], HASTA)
    assert resultado["instrumentos"] == []
    assert resultado["importeCompras"] == Decimal("0")
    assert resultado["rendimientoPorcentual"] is None
