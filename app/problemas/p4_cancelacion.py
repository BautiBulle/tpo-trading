"""Problema 4: cancelación y expiración con liberación de fondos."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.constantes import (
    CANCELADA, VENCIDA, PENDIENTE, PARCIAL,
    PARCIALMENTE_EJECUTADA, EN_CANCELACION,
)
from app.repos.mongo_repo import (
    obtener_orden, obtener_saga, crear_saga,
    cambiar_estado_saga, registrar_paso_saga,
    tomar_orden_para_cierre, finalizar_cierre_orden,
    listar_ordenes_vencidas,
)
from app.repos.saldo_pg import liberar_reserva_orden, revertir_liberacion_orden


def cancelar_orden(
    id_orden: UUID,
    id_cancelacion: UUID = None,
    forzar_falla: str = None,
):
    """Cancela una compra pendiente o parcial y devuelve la orden.

    forzar_falla puede ser 'ORDEN' o 'SALDO', igual que las fallas del P3.
    Las ejecuciones ya confirmadas se conservan.
    """
    return _cerrar_orden(id_orden, CANCELADA, id_cancelacion, forzar_falla)


def expirar_orden(
    id_orden: UUID,
    fecha_actual: datetime = None,
    id_cancelacion: UUID = None,
    forzar_falla: str = None,
):
    """Marca como vencida una compra cuya fecha de expiración ya llegó."""
    fecha_actual = _fecha_utc(fecha_actual)
    return _cerrar_orden(
        id_orden, VENCIDA, id_cancelacion, forzar_falla, fecha_actual
    )


def expirar_ordenes(fecha_actual: datetime = None):
    """Procesa vencimientos y devuelve las órdenes vencidas y los errores.

    Se llama desde la aplicación; no inicia un proceso automático.
    Una falla no impide intentar el vencimiento de las otras órdenes.
    """
    fecha_actual = _fecha_utc(fecha_actual)
    vencidas = []
    errores = []

    for orden in listar_ordenes_vencidas(fecha_actual):
        try:
            vencidas.append(expirar_orden(UUID(orden["_id"]), fecha_actual))
        except Exception as error:
            errores.append({"idOrden": orden["_id"], "error": str(error)})

    return {"vencidas": vencidas, "errores": errores}


def _fecha_utc(fecha):
    if fecha is None:
        return datetime.now(timezone.utc)
    if (
        not isinstance(fecha, datetime)
        or fecha.tzinfo is None
        or fecha.utcoffset() is None
    ):
        raise ValueError("La fecha debe ser datetime con zona horaria")
    return fecha.astimezone(timezone.utc)


def _cerrar_orden(
    id_orden, estado_final, id_cancelacion, forzar_falla, fecha_actual=None
):
    if not isinstance(id_orden, UUID):
        raise ValueError("id_orden debe ser UUID")
    if id_cancelacion is None:
        id_cancelacion = uuid4()
    elif not isinstance(id_cancelacion, UUID):
        raise ValueError("id_cancelacion debe ser UUID")
    if forzar_falla not in (None, "ORDEN", "SALDO"):
        raise ValueError("Escenario de falla desconocido")

    tipo_saga = "CANCELAR_ORDEN" if estado_final == CANCELADA else "EXPIRAR_ORDEN"
    saga = obtener_saga(id_cancelacion)
    if saga is not None:
        if saga["tipo"] != tipo_saga or saga["datos"]["idOrden"] != str(id_orden):
            raise ValueError("Cancelación repetida con datos diferentes")
        if saga["estado"] == "COMPLETADA":
            return obtener_orden(id_orden)
        raise RuntimeError("El cierre ya tiene una saga pendiente o fallida")

    orden = obtener_orden(id_orden)
    if orden is None:
        raise ValueError("La orden no existe")
    if orden["tipo"] != "COMPRA":
        raise ValueError("Solo se admiten órdenes de compra")
    if orden["estado"] == estado_final:
        return orden
    if orden["estado"] not in (PENDIENTE, PARCIALMENTE_EJECUTADA, PARCIAL):
        raise ValueError("La orden no admite cancelación o vencimiento")

    if estado_final == VENCIDA:
        vencimiento = orden.get("fechaExpiracion")
        if vencimiento is None:
            raise ValueError("La orden no tiene fecha de expiración")
        if _fecha_utc(vencimiento) > fecha_actual:
            raise ValueError("La orden todavía no venció")

    id_portafolio = UUID(orden["idPortafolio"])
    estado_anterior = orden["estado"]
    crear_saga(
        id_cancelacion,
        tipo_saga,
        {
            "idOrden": id_orden,
            "idPortafolio": id_portafolio,
            "estadoAnterior": estado_anterior,
            "estadoFinal": estado_final,
            "fechaEvaluacion": fecha_actual,
        },
    )

    liberacion_iniciada = False
    try:
        # 1. Impedir nuevas ejecuciones mientras se libera la reserva.
        tomada = tomar_orden_para_cierre(
            id_orden, id_cancelacion, estado_anterior, fecha_actual
        )
        if tomada is None:
            raise ValueError("La orden cambió o tiene una ejecución en curso")
        registrar_paso_saga(id_cancelacion, "TOMAR_ORDEN", "COMPLETADO")

        if forzar_falla == "ORDEN":
            raise RuntimeError("Falla simulada en orden")

        # 2. Liberar solo el dinero que sigue reservado para esta orden.
        liberacion_iniciada = True
        importe = liberar_reserva_orden(id_portafolio, id_orden, id_cancelacion)
        registrar_paso_saga(
            id_cancelacion, "LIBERAR_FONDOS", "COMPLETADO", {"importe": importe}
        )

        if forzar_falla == "SALDO":
            raise RuntimeError("Falla simulada en saldo")

        # 3. Confirmar juntos el estado de la orden y el de su saga.
        return finalizar_cierre_orden(
            id_orden, id_cancelacion, estado_final, "COMPLETADA"
        )

    except Exception:
        try:
            actual = obtener_orden(id_orden)
            es_propia = actual is not None and (
                actual.get("idCierre") == str(id_cancelacion)
            )
            # Mongo puede haber confirmado aunque se haya perdido la respuesta.
            if es_propia and actual["estado"] == estado_final:
                return actual

            if es_propia and actual["estado"] == EN_CANCELACION:
                # Consulta el movimiento real, incluso si liberar lanzó un error
                # después de confirmar la transacción en PostgreSQL.
                revertir_liberacion_orden(id_portafolio, id_orden, id_cancelacion)
                finalizar_cierre_orden(
                    id_orden, id_cancelacion, estado_anterior, "COMPENSADA"
                )
            else:
                estado = "REQUIERE_REVISION" if liberacion_iniciada else "FALLIDA"
                cambiar_estado_saga(id_cancelacion, estado)
        except Exception as error:
            # Si no se pudo volver a reservar el dinero, la orden permanece
            # tomada: no debe volver a ejecutarse con fondos insuficientes.
            try:
                cambiar_estado_saga(id_cancelacion, "REQUIERE_REVISION")
            except Exception:
                pass
            raise RuntimeError("Cierre fallido con compensación incompleta") from error
        raise
