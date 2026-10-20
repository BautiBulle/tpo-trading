"""Repositorio MongoDB: usuarios, instrumentos, portafolios, órdenes y sagas."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from bson.decimal128 import Decimal128
from pymongo import ReturnDocument

from app.config import get_mongo_db
from app.constantes import (
    PARCIAL, PENDIENTE, PARCIALMENTE_EJECUTADA,
    EN_CANCELACION, CANCELADA, VENCIDA,
)


COLECCIONES = (
    "usuarios",
    "operadores",
    "instrumentos",
    "portafolios",
    "ordenes",
    "sagas",
)


def _validar_uuid(valor, nombre):
    if not isinstance(valor, UUID):
        raise ValueError(f"{nombre} debe ser UUID")


def _validar_importe(valor, nombre):
    if not isinstance(valor, Decimal):
        raise ValueError(f"{nombre} debe ser Decimal")
    if not valor.is_finite() or valor < 0:
        raise ValueError(f"{nombre} debe ser finito y no negativo")


def _fecha_actual():
    return datetime.now(timezone.utc)


def _preparar_documento(documento):
    """Convierte UUID y Decimal a tipos compatibles con MongoDB."""
    if isinstance(documento, UUID):
        return str(documento)

    if isinstance(documento, Decimal):
        return Decimal128(documento)

    if isinstance(documento, dict):
        return {
            clave: _preparar_documento(valor)
            for clave, valor in documento.items()
        }

    if isinstance(documento, list):
        return [_preparar_documento(valor) for valor in documento]

    return documento


def _recuperar_documento(documento):
    """Recupera Decimal128 como Decimal."""
    if isinstance(documento, Decimal128):
        return documento.to_decimal()

    if isinstance(documento, dict):
        return {
            clave: _recuperar_documento(valor)
            for clave, valor in documento.items()
        }

    if isinstance(documento, list):
        return [_recuperar_documento(valor) for valor in documento]

    return documento


def guardar_documento(coleccion, documento):
    """Inserta un documento en una colección permitida."""
    if coleccion not in COLECCIONES:
        raise ValueError("Colección no permitida")

    if not isinstance(documento, dict) or "_id" not in documento:
        raise ValueError("El documento debe incluir _id")

    db = get_mongo_db()
    preparado = _preparar_documento(documento)

    db[coleccion].insert_one(preparado)
    return preparado["_id"]


def buscar_documento(coleccion, identificador):
    """Busca un documento por su identificador."""
    if coleccion not in COLECCIONES:
        raise ValueError("Colección no permitida")

    db = get_mongo_db()
    documento = db[coleccion].find_one(
        {"_id": _preparar_documento(identificador)}
    )

    if documento is None:
        return None

    return _recuperar_documento(documento)


# ---------- Usuarios ----------

def crear_usuario(id_usuario, nombre, email):
    _validar_uuid(id_usuario, "id_usuario")

    if not nombre or not email:
        raise ValueError("Nombre y email son obligatorios")

    return guardar_documento(
        "usuarios",
        {
            "_id": id_usuario,
            "nombre": nombre,
            "email": email,
            "fechaCreacion": _fecha_actual(),
        },
    )


def obtener_usuario(id_usuario):
    return buscar_documento("usuarios", id_usuario)


# ---------- Instrumentos ----------

def crear_instrumento(id_instrumento, simbolo, nombre, sector):
    _validar_uuid(id_instrumento, "id_instrumento")

    if not simbolo or not simbolo.strip():
        raise ValueError("El símbolo es obligatorio")

    return guardar_documento(
        "instrumentos",
        {
            "_id": id_instrumento,
            "simbolo": simbolo.strip(),
            "nombre": nombre,
            "sector": sector,
            "estado": "ACTIVO",
            "fechaCreacion": _fecha_actual(),
        },
    )


def obtener_instrumento(id_instrumento):
    return buscar_documento("instrumentos", id_instrumento)


def buscar_instrumento_por_simbolo(simbolo):
    db = get_mongo_db()
    documento = db["instrumentos"].find_one({"simbolo": simbolo})

    return (
        _recuperar_documento(documento)
        if documento is not None
        else None
    )


def suspender_instrumento(id_instrumento):
    """Marca un instrumento como suspendido."""
    db = get_mongo_db()

    documento = db["instrumentos"].find_one_and_update(
        {"_id": str(id_instrumento)},
        {"$set": {
            "estado": "SUSPENDIDO",
            "fechaSuspension": _fecha_actual(),
        }},
        return_document=ReturnDocument.AFTER,
    )

    return _recuperar_documento(documento) if documento else None


# ---------- Portafolios ----------

def crear_portafolio(id_portafolio, id_usuario):
    _validar_uuid(id_portafolio, "id_portafolio")
    _validar_uuid(id_usuario, "id_usuario")

    return guardar_documento(
        "portafolios",
        {
            "_id": id_portafolio,
            "idUsuario": str(id_usuario),
            "posiciones": [],
            "fechaCreacion": _fecha_actual(),
        },
    )


def obtener_portafolio(id_portafolio):
    return buscar_documento("portafolios", id_portafolio)


# ---------- Órdenes ----------

def crear_orden(
    id_orden,
    id_portafolio,
    id_instrumento,
    tipo,
    cantidad,
    precio_limite,
    fecha_expiracion=None,
):
    """Registra una orden pendiente de procesamiento."""
    _validar_uuid(id_orden, "id_orden")
    _validar_uuid(id_portafolio, "id_portafolio")
    _validar_uuid(id_instrumento, "id_instrumento")

    if tipo not in ("COMPRA", "VENTA"):
        raise ValueError("Tipo de orden inválido")

    _validar_importe(cantidad, "cantidad")
    _validar_importe(precio_limite, "precio_limite")

    if cantidad == 0 or precio_limite == 0:
        raise ValueError("Cantidad y precio deben ser positivos")

    if fecha_expiracion is not None:
        if (
            not isinstance(fecha_expiracion, datetime)
            or fecha_expiracion.tzinfo is None
            or fecha_expiracion.utcoffset() is None
        ):
            raise ValueError(
                "fecha_expiracion debe incluir zona horaria"
            )

    return guardar_documento(
        "ordenes",
        {
            "_id": id_orden,
            "idPortafolio": str(id_portafolio),
            "idInstrumento": str(id_instrumento),
            "tipo": tipo,
            "cantidad": cantidad,
            "precioLimite": precio_limite,
            "estado": "PENDIENTE",
            "cantidadEjecutada": Decimal128(Decimal("0")),
            "fechaCreacion": _fecha_actual(),
            "fechaExpiracion": fecha_expiracion,
        },
    )


def obtener_orden(id_orden):
    return buscar_documento("ordenes", id_orden)


def cambiar_estado_orden(id_orden, estado_anterior, estado_nuevo):
    """Actualiza el estado solo si coincide con el esperado."""
    db = get_mongo_db()

    documento = db["ordenes"].find_one_and_update(
        {
            "_id": str(id_orden),
            "estado": estado_anterior,
        },
        {
            "$set": {
                "estado": estado_nuevo,
                "fechaActualizacion": _fecha_actual(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    return _recuperar_documento(documento) if documento else None


def listar_ordenes_portafolio(id_portafolio):
    db = get_mongo_db()

    documentos = db["ordenes"].find(
        {"idPortafolio": str(id_portafolio)}
    ).sort("fechaCreacion", -1)

    return [_recuperar_documento(doc) for doc in documentos]


# ---------- Sagas ----------

def crear_saga(id_saga, tipo, datos=None):
    """Registra el inicio de una operación distribuida."""
    _validar_uuid(id_saga, "id_saga")

    return guardar_documento(
        "sagas",
        {
            "_id": id_saga,
            "tipo": tipo,
            "estado": "INICIADA",
            "datos": _preparar_documento(datos if datos is not None else {}),
            "pasos": [],
            "fechaCreacion": _fecha_actual(),
        },
    )


def registrar_paso_saga(id_saga, paso, estado, detalle=None):
    """Agrega un evento al historial de la saga."""
    db = get_mongo_db()

    documento = db["sagas"].find_one_and_update(
        {"_id": str(id_saga)},
        {
            "$push": {
                "pasos": {
                    "paso": paso,
                    "estado": estado,
                    "detalle": _preparar_documento(detalle),
                    "fechaHora": _fecha_actual(),
                }
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    return _recuperar_documento(documento) if documento else None


def cambiar_estado_saga(id_saga, estado):
    """Actualiza el estado general de una saga."""
    db = get_mongo_db()

    documento = db["sagas"].find_one_and_update(
        {"_id": str(id_saga)},
        {
            "$set": {
                "estado": estado,
                "fechaActualizacion": _fecha_actual(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )

    return _recuperar_documento(documento) if documento else None


def obtener_saga(id_saga):
    return buscar_documento("sagas", id_saga)


def reservar_ejecucion_orden(
    id_orden: UUID,
    id_ejecucion: UUID,
    cantidad: Decimal,
):
    """Reserva una cantidad para ejecutar, evitando sobre-ejecuciones.

    La operación se realiza en una transacción MongoDB.
    Requiere MongoDB replica set.
    """
    _validar_uuid(id_orden, "id_orden")
    _validar_uuid(id_ejecucion, "id_ejecucion")
    _validar_importe(cantidad, "cantidad")

    if cantidad == 0:
        raise ValueError("La cantidad debe ser positiva")

    db = get_mongo_db()

    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            orden = db.ordenes.find_one(
                {"_id": str(id_orden)},
                session=sesion,
            )

            if orden is None:
                raise ValueError("La orden no existe")

            if orden["estado"] not in (
                "PENDIENTE",
                "PARCIALMENTE_EJECUTADA",
            ):
                raise ValueError("La orden no admite ejecuciones")

            reservas = orden.get("reservasEjecucion", [])

            for reserva in reservas:
                if reserva["idEjecucion"] == str(id_ejecucion):
                    if reserva["cantidad"].to_decimal() != cantidad:
                        raise ValueError(
                            "Ejecución repetida con cantidad diferente"
                        )
                    return False

            ejecutada = orden.get(
                "cantidadEjecutada",
                Decimal128(Decimal("0")),
            ).to_decimal()

            reservada = sum(
                (
                    reserva["cantidad"].to_decimal()
                    for reserva in reservas
                ),
                Decimal("0"),
            )

            total = orden["cantidad"].to_decimal()

            if ejecutada + reservada + cantidad > total:
                raise ValueError(
                    "La ejecución supera la cantidad pendiente"
                )

            resultado = db.ordenes.update_one(
                {"_id": str(id_orden)},
                {
                    "$push": {
                        "reservasEjecucion": {
                            "idEjecucion": str(id_ejecucion),
                            "cantidad": Decimal128(cantidad),
                        }
                    },
                    "$set": {
                        "fechaActualizacion": _fecha_actual(),
                    },
                },
                session=sesion,
            )

            if resultado.modified_count != 1:
                raise RuntimeError(
                    "No se pudo reservar la ejecución"
                )

    return True


def confirmar_ejecucion_orden(
    id_orden: UUID,
    id_ejecucion: UUID,
):
    """Confirma una reserva y actualiza la cantidad ejecutada.

    Retorna False si la ejecución ya estaba confirmada.
    """
    _validar_uuid(id_orden, "id_orden")
    _validar_uuid(id_ejecucion, "id_ejecucion")

    db = get_mongo_db()
    identificador = str(id_ejecucion)

    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            orden = db.ordenes.find_one(
                {"_id": str(id_orden)},
                session=sesion,
            )

            if orden is None:
                raise ValueError("La orden no existe")

            confirmadas = orden.get("ejecucionesConfirmadas", [])

            if identificador in confirmadas:
                return False

            reservas = orden.get("reservasEjecucion", [])
            reserva = next(
                (
                    item for item in reservas
                    if item["idEjecucion"] == identificador
                ),
                None,
            )

            if reserva is None:
                raise ValueError(
                    "No existe una reserva para esta ejecución"
                )

            cantidad = reserva["cantidad"].to_decimal()
            ejecutada = orden.get(
                "cantidadEjecutada",
                Decimal128(Decimal("0")),
            ).to_decimal()
            total = orden["cantidad"].to_decimal()

            nueva_cantidad = ejecutada + cantidad

            if nueva_cantidad > total:
                raise ValueError(
                    "La ejecución supera la cantidad de la orden"
                )

            nuevo_estado = (
                "EJECUTADA"
                if nueva_cantidad == total
                else "PARCIALMENTE_EJECUTADA"
            )

            resultado = db.ordenes.update_one(
                {"_id": str(id_orden)},
                {
                    "$set": {
                        "cantidadEjecutada": Decimal128(nueva_cantidad),
                        "estado": nuevo_estado,
                        "fechaActualizacion": _fecha_actual(),
                    },
                    "$pull": {
                        "reservasEjecucion": {
                            "idEjecucion": identificador
                        }
                    },
                    "$addToSet": {
                        "ejecucionesConfirmadas": identificador
                    },
                },
                session=sesion,
            )

            if resultado.modified_count != 1:
                raise RuntimeError(
                    "No se pudo confirmar la ejecución"
                )

    return True


def liberar_reserva_ejecucion(
    id_orden: UUID,
    id_ejecucion: UUID,
):
    """Libera una reserva que no llegó a confirmarse.

    Es idempotente: repetir la liberación no modifica la orden.
    """
    _validar_uuid(id_orden, "id_orden")
    _validar_uuid(id_ejecucion, "id_ejecucion")

    db = get_mongo_db()
    identificador = str(id_ejecucion)

    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            orden = db.ordenes.find_one(
                {"_id": str(id_orden)},
                session=sesion,
            )

            if orden is None:
                raise ValueError("La orden no existe")

            if identificador in orden.get(
                "ejecucionesConfirmadas", []
            ):
                raise ValueError(
                    "No se puede liberar una ejecución confirmada"
                )

            resultado = db.ordenes.update_one(
                {
                    "_id": str(id_orden),
                    "reservasEjecucion.idEjecucion": identificador,
                },
                {
                    "$pull": {
                        "reservasEjecucion": {
                            "idEjecucion": identificador
                        }
                    },
                    "$set": {
                        "fechaActualizacion": _fecha_actual()
                    },
                },
                session=sesion,
            )

    return resultado.modified_count == 1


# ---------- Cancelación y vencimiento (P4) ----------

def tomar_orden_para_cierre(
    id_orden, id_cierre, estado_anterior, fecha_vencimiento=None
):
    """Toma una orden solo si no hay una ejecución reservada o en curso."""
    _validar_uuid(id_orden, "id_orden")
    _validar_uuid(id_cierre, "id_cierre")
    if estado_anterior not in (PENDIENTE, PARCIALMENTE_EJECUTADA, PARCIAL):
        raise ValueError("Estado no permitido para cerrar la orden")

    filtro = {
        "_id": str(id_orden),
        "tipo": "COMPRA",
        "estado": estado_anterior,
        "reservasEjecucion.0": {"$exists": False},
        "ejecucionEnCurso": {"$exists": False},
    }
    if fecha_vencimiento is not None:
        filtro["fechaExpiracion"] = {"$ne": None, "$lte": fecha_vencimiento}

    documento = get_mongo_db().ordenes.find_one_and_update(
        filtro,
        {"$set": {
            "estado": EN_CANCELACION,
            "idCierre": str(id_cierre),
            "fechaActualizacion": _fecha_actual(),
        }},
        return_document=ReturnDocument.AFTER,
    )
    return _recuperar_documento(documento) if documento else None


def finalizar_cierre_orden(id_orden, id_cierre, estado_orden, estado_saga):
    """Confirma el cierre o su compensación junto con la saga en MongoDB."""
    _validar_uuid(id_orden, "id_orden")
    _validar_uuid(id_cierre, "id_cierre")
    if not (
        (estado_saga == "COMPLETADA" and estado_orden in (CANCELADA, VENCIDA))
        or (estado_saga == "COMPENSADA" and estado_orden in (
            PENDIENTE, PARCIALMENTE_EJECUTADA, PARCIAL
        ))
    ):
        raise ValueError("Estados de cierre inválidos")

    db = get_mongo_db()
    fecha = _fecha_actual()
    cambios = {"$set": {"estado": estado_orden, "fechaActualizacion": fecha}}
    if estado_saga == "COMPENSADA":
        cambios["$unset"] = {"idCierre": ""}

    with db.client.start_session() as sesion:
        with sesion.start_transaction():
            documento = db.ordenes.find_one_and_update(
                {"_id": str(id_orden), "estado": EN_CANCELACION,
                 "idCierre": str(id_cierre)},
                cambios,
                return_document=ReturnDocument.AFTER,
                session=sesion,
            )
            if documento is None:
                raise ValueError("La orden ya no pertenece a este cierre")

            resultado = db.sagas.update_one(
                {"_id": str(id_cierre), "datos.idOrden": str(id_orden)},
                {
                    "$set": {"estado": estado_saga, "fechaActualizacion": fecha},
                    "$push": {"pasos": {
                        "paso": "CERRAR_ORDEN" if estado_saga == "COMPLETADA"
                        else "RESTAURAR_ORDEN",
                        "estado": "COMPLETADO",
                        "detalle": {"estadoOrden": estado_orden},
                        "fechaHora": fecha,
                    }},
                },
                session=sesion,
            )
            if resultado.matched_count != 1:
                raise ValueError("La saga del cierre no existe")

    return _recuperar_documento(documento)


def listar_ordenes_vencidas(fecha_actual):
    """Busca compras pendientes o parciales con vencimiento alcanzado."""
    if (
        not isinstance(fecha_actual, datetime)
        or fecha_actual.tzinfo is None
        or fecha_actual.utcoffset() is None
    ):
        raise ValueError("fecha_actual debe incluir zona horaria")
    cursor = get_mongo_db().ordenes.find({
        "tipo": "COMPRA",
        "estado": {"$in": [PENDIENTE, PARCIALMENTE_EJECUTADA, PARCIAL]},
        "fechaExpiracion": {"$ne": None, "$lte": fecha_actual},
    }).sort("fechaExpiracion", 1)
    return [_recuperar_documento(orden) for orden in cursor]
