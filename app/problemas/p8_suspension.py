"""P8: suspensión recuperable y trazabilidad multibase de órdenes.

La suspensión es una saga de avance: ante fallas conserva EN_SUSPENSION
para impedir nuevas compras y permite reanudar con el mismo identificador.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4, uuid5

from bson.decimal128 import Decimal128

from app.config import get_mongo_db
from app.problemas.p4_cancelacion import cancelar_orden
from app.repos.mongo_repo import obtener_instrumento, obtener_orden, obtener_portafolio
from app.repos.historial_cass import (
    registrar_auditoria, consultar_operaciones_instrumento, consultar_precios,
)
from app.repos.precios_redis import get_precio
from app.repos.posiciones_mongo import obtener_posicion
from app.repos.saldo_pg import consultar_saldo


def suspender_instrumento(id_instrumento: UUID, id_operador: UUID,
                          motivo: str, id_suspension: UUID = None,
                          forzar_falla: str = None):
    """Bloquea el instrumento, cancela órdenes y audita; reanudable.

    forzar_falla: DESPUES_BLOQUEO, DESPUES_CANCELACION o AUDITORIA.
    No reactiva el instrumento al fallar: se reintenta con id_suspension.
    """
    if not isinstance(id_instrumento, UUID) or not isinstance(id_operador, UUID):
        raise ValueError("Los identificadores deben ser UUID")
    if not isinstance(motivo, str) or not motivo.strip():
        raise ValueError("El motivo es obligatorio")
    if forzar_falla not in (None, "DESPUES_BLOQUEO", "DESPUES_CANCELACION", "AUDITORIA"):
        raise ValueError("Falla simulada desconocida")
    id_suspension = id_suspension or uuid4()
    if not isinstance(id_suspension, UUID):
        raise ValueError("id_suspension debe ser UUID")

    db = get_mongo_db()
    instrumento = obtener_instrumento(id_instrumento)
    if instrumento is None:
        raise ValueError("Instrumento inexistente")
    saga_id = str(id_suspension)
    datos = {"idInstrumento": str(id_instrumento), "idOperador": str(id_operador),
             "motivo": motivo.strip()}
    saga = db.sagas.find_one({"_id": saga_id})
    fecha_inicio = (saga.get("fechaCreacion") if saga else None) or datetime.now(timezone.utc)
    if saga is None:
        # La saga se registra antes de modificar el instrumento.
        db.sagas.insert_one({"_id": saga_id, "tipo": "SUSPENDER_INSTRUMENTO",
                             "estado": "INICIADA", "datos": datos,
                             "pasos": [], "fechaCreacion": fecha_inicio})
    elif saga.get("tipo") != "SUSPENDER_INSTRUMENTO" or saga.get("datos") != datos:
        raise ValueError("Suspensión repetida con datos diferentes")
    elif saga.get("estado") == "COMPLETADA":
        return {"idSuspension": saga_id, "estado": "SUSPENDIDO", "canceladas": []}

    # Toma exclusiva: otras suspensiones no pueden apropiarse del instrumento.
    tomado = db.instrumentos.find_one_and_update(
        {"_id": str(id_instrumento), "$or": [
            {"estado": "ACTIVO"},
            {"estado": "EN_SUSPENSION", "idSuspension": saga_id},
        ]},
        {"$set": {"estado": "EN_SUSPENSION", "idSuspension": saga_id}},
    )
    if tomado is None:
        raise ValueError("Instrumento suspendido o tomado por otra suspensión")

    canceladas = []
    try:
        if forzar_falla == "DESPUES_BLOQUEO":
            raise RuntimeError("Falla simulada después del bloqueo")
        # P4 usa transición atómica de orden y liberación de fondos en PG.
        ordenes = db.ordenes.find({
            "idInstrumento": str(id_instrumento), "tipo": "COMPRA",
            "estado": {"$in": ["PENDIENTE", "PARCIALMENTE_EJECUTADA", "PARCIAL"]},
        })
        for orden in ordenes:
            id_orden = UUID(orden["_id"])
            id_cancelacion = uuid5(id_suspension, f"cancelar:{id_orden}")
            try:
                cancelar_orden(id_orden, id_cancelacion=id_cancelacion)
            except RuntimeError:
                # P4 marca la saga como COMPENSADA ante falla. Para poder
                # reintentar se necesita un nuevo id si quedó compensada.
                cierre = db.sagas.find_one({"_id": str(id_cancelacion)})
                if cierre and cierre.get("estado") == "COMPENSADA":
                    cancelar_orden(id_orden, id_cancelacion=uuid4())
                else:
                    raise
            canceladas.append(str(id_orden))
            if forzar_falla == "DESPUES_CANCELACION":
                raise RuntimeError("Falla simulada después de cancelar")

        # No confirmar si quedan órdenes abiertas o cierres en curso.
        restantes = db.ordenes.count_documents({
            "idInstrumento": str(id_instrumento), "tipo": "COMPRA",
            "estado": {"$in": ["PENDIENTE", "PARCIALMENTE_EJECUTADA", "PARCIAL", "EN_CANCELACION"]},
        })
        if restantes:
            raise RuntimeError(f"Quedan {restantes} órdenes por cerrar")

        if forzar_falla == "AUDITORIA":
            raise RuntimeError("Falla simulada de auditoría")
        # Clave estable para que reintentos no dupliquen el evento Cassandra.
        registrar_auditoria(instrumento["simbolo"],
                           fecha_inicio,
                           id_suspension, "SUSPENSION", motivo.strip(), id_operador)
        confirmacion = db.instrumentos.update_one(
            {"_id": str(id_instrumento), "estado": "EN_SUSPENSION",
             "idSuspension": saga_id},
            {"$set": {"estado": "SUSPENDIDO", "fechaSuspension": datetime.now(timezone.utc)}})
        if confirmacion.matched_count != 1:
            raise RuntimeError("No se pudo confirmar la suspensión")
        db.sagas.update_one({"_id": saga_id}, {"$set": {"estado": "COMPLETADA"}})
        return {"idSuspension": saga_id, "estado": "SUSPENDIDO", "canceladas": canceladas}
    except Exception:
        db.sagas.update_one({"_id": saga_id}, {"$set": {"estado": "REQUIERE_REVISION"}})
        raise


def trazar_orden(id_orden: UUID, margen_segundos: int = 1):
    """Traza una orden y sus ejecuciones confirmadas sin atribuciones por coincidencia temporal."""
    if not isinstance(id_orden, UUID):
        raise ValueError("id_orden debe ser UUID")
    if not isinstance(margen_segundos, int) or isinstance(margen_segundos, bool) or margen_segundos < 1:
        raise ValueError("margen_segundos debe ser un entero positivo")
    orden = obtener_orden(id_orden)
    if orden is None:
        raise ValueError("La orden no existe")
    instrumento = obtener_instrumento(UUID(orden["idInstrumento"]))
    portafolio = obtener_portafolio(UUID(orden["idPortafolio"]))
    if not instrumento or not portafolio:
        raise ValueError("Faltan referencias de la orden")
    simbolo = instrumento["simbolo"]
    db = get_mongo_db()
    # La vinculación exacta con la orden se obtiene desde las sagas Mongo.
    sagas = list(db.sagas.find({"datos.idOrden": str(id_orden)}))
    confirmadas = {str(x) for x in orden.get("ejecucionesConfirmadas", [])}
    ejecuciones = []
    for saga in sagas:
        datos = {clave: (valor.to_decimal() if isinstance(valor, Decimal128) else valor)
                 for clave, valor in saga.get("datos", {}).items()}
        ejecucion_id = datos.get("idEjecucion")
        if not ejecucion_id or str(ejecucion_id) not in confirmadas:
            continue
        fecha = datos.get("fechaHora") or datos.get("fechaEjecucion")
        resultado = {"idEjecucion": str(ejecucion_id), "saga": str(saga["_id"]),
                     "estadoSaga": saga.get("estado"), "fechaHora": fecha,
                     "cantidad": datos.get("cantidad"),
                     # Precio vigente en Redis al ejecutar (el P3 ejecuta a ese precio).
                     "precioVigenteAlEjecutar": datos.get("precioVigente") or datos.get("precio"),
                     "importe": datos.get("importe"),
                     "precioHistorico": None, "operacionHistorica": None}
        if isinstance(fecha, datetime) and fecha.tzinfo is not None:
            desde = fecha - timedelta(seconds=margen_segundos)
            hasta = fecha + timedelta(seconds=margen_segundos + 1)
            ops = consultar_operaciones_instrumento(simbolo, desde, hasta)
            resultado["operacionHistorica"] = next(
                (op for op in ops if str(op["id_operacion"]) == str(ejecucion_id)), None)
            precios = consultar_precios(simbolo, desde, hasta)
            resultado["precioHistorico"] = min(
                precios, key=lambda p: abs((p["fecha_hora"] - fecha).total_seconds()),
                default=None)
        ejecuciones.append(resultado)
    return {"orden": orden, "instrumento": instrumento,
            "precioVigente": get_precio(simbolo), "ejecuciones": ejecuciones,
            "ejecucionesConfirmadas": sorted(confirmadas),
            "trazabilidadCompleta": (len(ejecuciones) == len(confirmadas) and
                all(e["operacionHistorica"] is not None for e in ejecuciones)),
            "posicionActual": obtener_posicion(UUID(orden["idPortafolio"]), UUID(orden["idInstrumento"])),
            "saldoActual": consultar_saldo(UUID(orden["idPortafolio"]))}
