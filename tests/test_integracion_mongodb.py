"""Pruebas de integración del repositorio MongoDB."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.config import get_mongo_db
from app.repos.mongo_repo import (
    buscar_documento,
    buscar_instrumento_por_simbolo,
    cambiar_estado_orden,
    cambiar_estado_saga,
    crear_instrumento,
    crear_orden,
    crear_portafolio,
    crear_saga,
    crear_usuario,
    listar_ordenes_portafolio,
    obtener_instrumento,
    obtener_orden,
    obtener_portafolio,
    obtener_saga,
    obtener_usuario,
    registrar_paso_saga,
    suspender_instrumento,
)


@pytest.fixture
def limpieza():
    """Registra documentos temporales y los elimina al finalizar."""
    creados = []
    yield creados

    db = get_mongo_db()
    for coleccion, identificador in creados:
        db[coleccion].delete_one({"_id": str(identificador)})


def test_crear_y_obtener_usuario(limpieza):
    identificador = uuid4()
    limpieza.append(("usuarios", identificador))

    crear_usuario(identificador, "Usuario Prueba", "prueba@example.com")
    usuario = obtener_usuario(identificador)

    assert usuario["_id"] == str(identificador)
    assert usuario["nombre"] == "Usuario Prueba"


def test_crear_y_buscar_instrumento(limpieza):
    identificador = uuid4()
    simbolo = f"TEST-{uuid4().hex[:12]}"
    limpieza.append(("instrumentos", identificador))

    crear_instrumento(identificador, simbolo, "Empresa Prueba", "Tecnologia")

    instrumento = obtener_instrumento(identificador)
    encontrado = buscar_instrumento_por_simbolo(simbolo)

    assert instrumento["simbolo"] == simbolo
    assert encontrado["_id"] == str(identificador)
    assert instrumento["estado"] == "ACTIVO"


def test_suspender_instrumento(limpieza):
    identificador = uuid4()
    simbolo = f"TEST-{uuid4().hex[:12]}"
    limpieza.append(("instrumentos", identificador))

    crear_instrumento(identificador, simbolo, "Empresa", "Energia")

    instrumento = suspender_instrumento(identificador)

    assert instrumento["estado"] == "SUSPENDIDO"


def test_crear_y_obtener_portafolio(limpieza):
    identificador = uuid4()
    usuario = uuid4()
    limpieza.append(("portafolios", identificador))

    crear_portafolio(identificador, usuario)
    portafolio = obtener_portafolio(identificador)

    assert portafolio["_id"] == str(identificador)
    assert portafolio["idUsuario"] == str(usuario)
    assert portafolio["posiciones"] == []



def test_crear_y_obtener_orden(limpieza):
    identificador = uuid4()
    id_instrumento = uuid4()

    limpieza.append(("ordenes", identificador))
    limpieza.append(("instrumentos", id_instrumento))

    crear_instrumento(
        id_instrumento,
        f"TEST-{uuid4().hex[:12]}",
        "Empresa Prueba",
        "Tecnologia",
    )

    crear_orden(
        identificador,
        uuid4(),
        id_instrumento,
        "COMPRA",
        Decimal("10"),
        Decimal("150.50"),
    )

    orden = obtener_orden(identificador)

    assert orden["estado"] == "PENDIENTE"
    assert orden["cantidad"] == Decimal("10")
    assert orden["precioLimite"] == Decimal("150.50")


def test_cambiar_estado_orden(limpieza):
    identificador = uuid4()
    id_instrumento = uuid4()

    limpieza.append(("ordenes", identificador))
    limpieza.append(("instrumentos", id_instrumento))

    crear_instrumento(
        id_instrumento,
        f"TEST-{uuid4().hex[:12]}",
        "Empresa Prueba",
        "Tecnologia",
    )

    crear_orden(
        identificador, uuid4(), id_instrumento,
        "COMPRA", Decimal("2"), Decimal("100"),
    )

    resultado = cambiar_estado_orden(
        identificador, "PENDIENTE", "EJECUTADA"
    )

    assert resultado["estado"] == "EJECUTADA"

    segundo = cambiar_estado_orden(
        identificador, "PENDIENTE", "CANCELADA"
    )
    assert segundo is None


def test_listar_ordenes_portafolio(limpieza):
    portafolio = uuid4()
    orden = uuid4()
    id_instrumento = uuid4()

    limpieza.append(("ordenes", orden))
    limpieza.append(("instrumentos", id_instrumento))

    crear_instrumento(
        id_instrumento,
        f"TEST-{uuid4().hex[:12]}",
        "Empresa Prueba",
        "Tecnologia",
    )

    crear_orden(
        orden, portafolio, id_instrumento,
        "COMPRA", Decimal("1"), Decimal("50"),
    )

    ordenes = listar_ordenes_portafolio(portafolio)

    assert any(doc["_id"] == str(orden) for doc in ordenes)


def test_crear_y_obtener_saga(limpieza):
    identificador = uuid4()
    limpieza.append(("sagas", identificador))

    crear_saga(
        identificador,
        "COLOCAR_ORDEN",
        {"importe": Decimal("150.50"), "idOrden": uuid4()},
    )

    saga = obtener_saga(identificador)

    assert saga["estado"] == "INICIADA"
    assert saga["datos"]["importe"] == Decimal("150.50")
    assert isinstance(saga["datos"]["idOrden"], str)


def test_registrar_paso_y_finalizar_saga(limpieza):
    identificador = uuid4()
    limpieza.append(("sagas", identificador))

    crear_saga(identificador, "COLOCAR_ORDEN")

    resultado = registrar_paso_saga(
        identificador,
        "RESERVAR_FONDOS",
        "COMPLETADO",
        {"importe": Decimal("200.00")},
    )

    assert len(resultado["pasos"]) == 1
    assert resultado["pasos"][0]["detalle"]["importe"] == Decimal("200.00")

    final = cambiar_estado_saga(identificador, "COMPLETADA")

    assert final["estado"] == "COMPLETADA"


def test_documento_inexistente():
    assert buscar_documento("usuarios", uuid4()) is None


def test_rechazar_coleccion_no_permitida():
    with pytest.raises(ValueError, match="Colección no permitida"):
        buscar_documento("otra_coleccion", uuid4())


def test_rechazar_orden_con_cantidad_cero():
    with pytest.raises(ValueError):
        crear_orden(
            uuid4(), uuid4(), uuid4(),
            "COMPRA", Decimal("0"), Decimal("100"),
        )
