"""Integración real del Problema 2 con MongoDB, PostgreSQL y Redis."""

from decimal import Decimal
from uuid import uuid4

from app.config import get_mongo_db
from app.problemas.p2_colocar_orden import colocar_orden_compra
from app.repos.precios_redis import set_precio
from app.repos.saldo_pg import consultar_saldo


def test_compra_real_con_reserva_de_fondos():
    db = get_mongo_db()

    # Datos iniciales generados por seed/cargar_datos.py.
    instrumento = db.instrumentos.find_one({"simbolo": "ACT001"})
    assert instrumento is not None

    portafolio = db.portafolios.find_one()
    assert portafolio is not None

    from uuid import UUID
    from datetime import datetime, timezone

    id_portafolio = UUID(portafolio["_id"])
    id_instrumento = UUID(instrumento["_id"])
    id_orden = uuid4()

    # Precio controlado para que la prueba sea reproducible.
    set_precio(
        "ACT001",
        Decimal("99.00"),
        Decimal("100.00"),
        Decimal("99.50"),
        datetime.now(timezone.utc),
    )

    saldo_antes = consultar_saldo(id_portafolio)
    assert saldo_antes is not None

    orden = colocar_orden_compra(
        id_portafolio=id_portafolio,
        id_instrumento=id_instrumento,
        cantidad=Decimal("2"),
        precio_limite=Decimal("110.00"),
        id_orden=id_orden,
    )

    assert orden is not None
    assert orden["_id"] == str(id_orden)
    assert orden["estado"] == "PENDIENTE"

    saldo_despues = consultar_saldo(id_portafolio)

    importe_reservado = Decimal("220.00")

    assert (
        saldo_despues["disponible"]
        == saldo_antes["disponible"] - importe_reservado
    )

    assert (
        saldo_despues["bloqueado"]
        == saldo_antes["bloqueado"] + importe_reservado
    )

    # Reintentar no debe reservar dinero nuevamente.
    orden_repetida = colocar_orden_compra(
        id_portafolio=id_portafolio,
        id_instrumento=id_instrumento,
        cantidad=Decimal("2"),
        precio_limite=Decimal("110.00"),
        id_orden=id_orden,
    )

    assert orden_repetida["_id"] == orden["_id"]
    assert consultar_saldo(id_portafolio) == saldo_despues

    # Verificar que la saga quedó registrada.
    saga = db.sagas.find_one({
        "datos.idOrden": str(id_orden)
    })

    assert saga is not None
    assert saga["estado"] == "COMPLETADA"
