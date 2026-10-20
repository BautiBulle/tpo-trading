"""Problema 3: ejecución total o parcial con compensaciones."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.repos.mongo_repo import (
    obtener_orden,
    obtener_portafolio,
    obtener_instrumento,
    crear_saga,
    obtener_saga,
    registrar_paso_saga,
    cambiar_estado_saga,
    reservar_ejecucion_orden,
    confirmar_ejecucion_orden,
    liberar_reserva_ejecucion,
)
from app.repos.posiciones_mongo import aplicar_compra, revertir_compra
from app.repos.historial_cass import registrar_operacion, revertir_operacion
from app.repos.saldo_pg import consumir, revertir_consumo


def ejecutar_orden_compra(
    id_orden: UUID,
    cantidad: Decimal,
    id_ejecucion: UUID = None,
    forzar_falla: str = None,
):
    """Ejecuta una compra total o parcial al precio límite.

    forzar_falla:
      'POSICION'  -> falla después de actualizar la posición.
      'HISTORIAL' -> falla después de escribir Cassandra.
      'SALDO'     -> falla después de consumir fondos.

    Se conserva la saga y se compensan los pasos aplicados.
    """
    if not isinstance(id_orden, UUID):
        raise ValueError("id_orden debe ser UUID")
    if not isinstance(cantidad, Decimal):
        raise ValueError("cantidad debe ser Decimal")
    if not cantidad.is_finite() or cantidad <= 0:
        raise ValueError("cantidad debe ser positiva y finita")

    if forzar_falla not in (None, "POSICION", "HISTORIAL", "SALDO"):
        raise ValueError("Escenario de falla desconocido")

    id_ejecucion = id_ejecucion or uuid4()
    if not isinstance(id_ejecucion, UUID):
        raise ValueError("id_ejecucion debe ser UUID")

    orden = obtener_orden(id_orden)
    if orden is None:
        raise ValueError("La orden no existe")
    if orden["tipo"] != "COMPRA":
        raise ValueError("Solo se admiten órdenes de compra")

    id_portafolio = UUID(orden["idPortafolio"])
    id_instrumento = UUID(orden["idInstrumento"])
    precio = orden["precioLimite"]
    importe = (cantidad * precio).quantize(Decimal("0.01"))

    if importe <= 0:
        raise ValueError("El importe de ejecución debe ser positivo")

    portafolio = obtener_portafolio(id_portafolio)
    instrumento = obtener_instrumento(id_instrumento)
    if portafolio is None or instrumento is None:
        raise ValueError("Portafolio o instrumento inexistente")
    if instrumento["estado"] != "ACTIVO":
        raise ValueError("El instrumento está suspendido")

    id_usuario = UUID(portafolio["idUsuario"])
    simbolo = instrumento["simbolo"]

    # Identificadores estables para reintentos.
    id_saga = id_ejecucion
    fecha = datetime.now(timezone.utc)

    saga = obtener_saga(id_saga)
    if saga is not None:
        if saga["estado"] == "COMPLETADA":
            return obtener_orden(id_orden)
        raise RuntimeError(
            "La ejecución ya tiene una saga pendiente o fallida"
        )

    crear_saga(
        id_saga,
        "EJECUTAR_ORDEN",
        {
            "idOrden": id_orden,
            "idEjecucion": id_ejecucion,
            "idPortafolio": id_portafolio,
            "idInstrumento": id_instrumento,
            "idUsuario": id_usuario,
            "simbolo": simbolo,
            "cantidad": cantidad,
            "precio": precio,
            "importe": importe,
            "fechaHora": fecha,
        },
    )

    reserva_iniciada = False
    posicion_iniciada = False
    historial_iniciado = False
    consumo_iniciado = False

    try:
        # 1. Reservar cantidad sin superar la orden.
        reserva_iniciada = True
        reservar_ejecucion_orden(
            id_orden, id_ejecucion, cantidad
        )
        registrar_paso_saga(
            id_saga, "RESERVAR_CANTIDAD", "COMPLETADO"
        )

        # 2. Actualizar posición.
        posicion_iniciada = True
        aplicar_compra(
            id_portafolio,
            id_instrumento,
            cantidad,
            precio,
            id_ejecucion,
        )
        registrar_paso_saga(
            id_saga, "ACTUALIZAR_POSICION", "COMPLETADO"
        )

        if forzar_falla == "POSICION":
            raise RuntimeError("Falla simulada en posición")

        # 3. Registrar historial auditable.
        historial_iniciado = True
        registrar_operacion(
            id_ejecucion,
            id_usuario,
            simbolo,
            fecha,
            "COMPRA",
            cantidad,
            precio,
        )
        registrar_paso_saga(
            id_saga, "REGISTRAR_HISTORIAL", "COMPLETADO"
        )

        if forzar_falla == "HISTORIAL":
            raise RuntimeError("Falla simulada en historial")

        # 4. Consumir saldo bloqueado.
        consumo_iniciado = True
        consumir(
            id_portafolio,
            importe,
            id_ejecucion,
            id_orden,
        )
        registrar_paso_saga(
            id_saga, "CONSUMIR_SALDO", "COMPLETADO"
        )

        if forzar_falla == "SALDO":
            raise RuntimeError("Falla simulada en saldo")

        # 5. Confirmar ejecución.
        confirmar_ejecucion_orden(id_orden, id_ejecucion)
        registrar_paso_saga(
            id_saga, "CONFIRMAR_EJECUCION", "COMPLETADO"
        )
        cambiar_estado_saga(id_saga, "COMPLETADA")

        return obtener_orden(id_orden)

    except Exception:
        errores_compensacion = []

        # Compensar en orden inverso.
        if consumo_iniciado:
            try:
                revertir_consumo(
                    id_portafolio,
                    importe,
                    id_ejecucion,
                    id_orden,
                )
            except ValueError as error:
                # Puede no haberse aplicado el consumo.
                if "No existe un consumo" not in str(error):
                    errores_compensacion.append(str(error))
            except Exception as error:
                errores_compensacion.append(str(error))

        if historial_iniciado:
            try:
                revertir_operacion(
                    id_ejecucion,
                    id_usuario,
                    simbolo,
                    fecha,
                )
            except Exception as error:
                errores_compensacion.append(str(error))

        if posicion_iniciada:
            try:
                revertir_compra(id_ejecucion)
            except Exception as error:
                errores_compensacion.append(str(error))

        if reserva_iniciada:
            try:
                liberar_reserva_ejecucion(
                    id_orden, id_ejecucion
                )
            except Exception as error:
                errores_compensacion.append(str(error))

        estado = (
            "REQUIERE_REVISION"
            if errores_compensacion
            else "COMPENSADA"
        )

        try:
            registrar_paso_saga(
                id_saga,
                "ROLLBACK",
                estado,
                {"errores": errores_compensacion},
            )
            cambiar_estado_saga(id_saga, estado)
        except Exception:
            pass

        if errores_compensacion:
            raise RuntimeError(
                "Ejecución fallida con compensación incompleta: "
                + "; ".join(errores_compensacion)
            )

        raise
