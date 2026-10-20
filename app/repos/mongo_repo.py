"""Repositorio MongoDB: usuarios, instrumentos, portafolios, órdenes y sagas."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from bson.decimal128 import Decimal128
from pymongo import ReturnDocument

from app.config import get_mongo_db


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
