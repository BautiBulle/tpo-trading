"""Gestión de posiciones del portafolio en MongoDB."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from bson.decimal128 import Decimal128
from app.config import get_mongo_db


def _validar_uuid(valor, nombre):
    if not isinstance(valor, UUID):
        raise ValueError(f"{nombre} debe ser UUID")


def _validar_cantidad(cantidad):
    if not isinstance(cantidad, Decimal):
        raise ValueError("La cantidad debe ser Decimal")
    if not cantidad.is_finite() or cantidad <= 0:
        raise ValueError("La cantidad debe ser positiva y finita")


def obtener_posicion(id_portafolio: UUID, id_instrumento: UUID):
    """Devuelve la posición o None si todavía no existe."""
    _validar_uuid(id_portafolio, "id_portafolio")
    _validar_uuid(id_instrumento, "id_instrumento")

    return get_mongo_db().posiciones.find_one({
        "idPortafolio": str(id_portafolio),
        "idInstrumento": str(id_instrumento),
    })


def listar_posiciones_portafolio(id_portafolio: UUID) -> list[dict]:
    """Lee las posiciones que escribe el P3 y convierte los importes a Decimal."""
    _validar_uuid(id_portafolio, "id_portafolio")
    documentos = get_mongo_db().posiciones.find({
        "idPortafolio": str(id_portafolio),
    }).sort("idInstrumento", 1)

    posiciones = []
    for documento in documentos:
        posiciones.append({
            "idInstrumento": documento["idInstrumento"],
            "cantidad": documento["cantidad"].to_decimal(),
            "precioPromedio": documento["precioPromedio"].to_decimal(),
        })
    return posiciones


def aplicar_compra(
    id_portafolio: UUID,
    id_instrumento: UUID,
    cantidad: Decimal,
    precio: Decimal,
    id_ejecucion: UUID,
):
    """Actualiza una posición y registra la ejecución aplicada.

    La transacción MongoDB evita aplicar dos veces el mismo id_ejecucion.
    Requiere MongoDB configurado como replica set.
    """
    _validar_uuid(id_portafolio, "id_portafolio")
    _validar_uuid(id_instrumento, "id_instrumento")
    _validar_uuid(id_ejecucion, "id_ejecucion")
    _validar_cantidad(cantidad)
    _validar_cantidad(precio)

    db = get_mongo_db()
    cliente = db.client

    with cliente.start_session() as sesion:
        with sesion.start_transaction():
            if db.movimientos_posicion.find_one(
                {"_id": str(id_ejecucion)}, session=sesion
            ):
                return False

            filtro = {
                "idPortafolio": str(id_portafolio),
                "idInstrumento": str(id_instrumento),
            }

            posicion = db.posiciones.find_one(
                filtro, session=sesion
            )

            cantidad_anterior = (
                Decimal(str(posicion["cantidad"].to_decimal()))
                if posicion else Decimal("0")
            )
            costo_anterior = (
                Decimal(str(posicion["precioPromedio"].to_decimal()))
                if posicion else Decimal("0")
            )

            cantidad_nueva = cantidad_anterior + cantidad
            precio_promedio = (
                (cantidad_anterior * costo_anterior + cantidad * precio)
                / cantidad_nueva
            )

            db.posiciones.update_one(
                filtro,
                {
                    "$set": {
                        **filtro,
                        "cantidad": Decimal128(cantidad_nueva),
                        "precioPromedio": Decimal128(precio_promedio),
                        "fechaActualizacion": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
                session=sesion,
            )

            db.movimientos_posicion.insert_one(
                {
                    "_id": str(id_ejecucion),
                    **filtro,
                    "cantidad": Decimal128(cantidad),
                    "precio": Decimal128(precio),
                    "cantidadAnterior": Decimal128(cantidad_anterior),
                    "precioPromedioAnterior": Decimal128(costo_anterior),
                    "estado": "APLICADO",
                },
                session=sesion,
            )

    return True


def revertir_compra(id_ejecucion: UUID):
    """Revierte una compra aplicada, sin repetir la compensación.

    Por seguridad, solo permite revertir si no hubo otro movimiento
    posterior sobre la misma posición.
    """
    _validar_uuid(id_ejecucion, "id_ejecucion")

    db = get_mongo_db()

    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            movimiento = db.movimientos_posicion.find_one(
                {"_id": str(id_ejecucion)}, session=sesion
            )

            if movimiento is None:
                return False

            if movimiento["estado"] == "REVERTIDO":
                return False

            filtro = {
                "idPortafolio": movimiento["idPortafolio"],
                "idInstrumento": movimiento["idInstrumento"],
            }

            posicion = db.posiciones.find_one(
                filtro, session=sesion
            )
            if posicion is None:
                raise RuntimeError("No existe la posición a revertir")

            cantidad_actual = posicion["cantidad"].to_decimal()
            cantidad_esperada = (
                movimiento["cantidadAnterior"].to_decimal()
                + movimiento["cantidad"].to_decimal()
            )

            if cantidad_actual != cantidad_esperada:
                raise RuntimeError(
                    "La posición cambió; requiere revisión manual"
                )

            db.posiciones.update_one(
                filtro,
                {
                    "$set": {
                        "cantidad": movimiento["cantidadAnterior"],
                        "precioPromedio": movimiento[
                            "precioPromedioAnterior"
                        ],
                        "fechaActualizacion": datetime.now(timezone.utc),
                    }
                },
                session=sesion,
            )

            db.movimientos_posicion.update_one(
                {"_id": str(id_ejecucion)},
                {"$set": {"estado": "REVERTIDO"}},
                session=sesion,
            )

    return True
