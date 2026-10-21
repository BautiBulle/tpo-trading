"""Problema 3: ejecución total o parcial con compensaciones.

La orden se ejecuta contra el precio vigente (precio de venta en Redis),
que debe ser menor o igual al precio límite. La orden había reservado
cantidad x precio límite; cuando se completa, se libera el sobrante.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4, uuid5

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
from app.repos.precios_redis import get_precio
from app.repos.saldo_pg import consumir, revertir_consumo, liberar_reserva_orden


def _precio_ejecucion(simbolo, precio_limite):
    """Precio vigente al que se ejecuta una compra (precio de venta)."""
    cotizacion = get_precio(simbolo)
    if cotizacion is None:
        raise ValueError(f"No existe cotización vigente para {simbolo}")
    precio = cotizacion["venta"]
    if precio > precio_limite:
        raise ValueError(
            f"El precio vigente ({precio}) supera el precio límite "
            f"({precio_limite}): la orden no se ejecuta"
        )
    return precio


def _liberar_sobrante(id_saga, id_portafolio, id_orden):
    """Libera lo que quedó bloqueado de una orden ya completada.

    El identificador depende solo de la orden: si dos ejecuciones la ven
    completa, la liberación se aplica una sola vez.
    """
    try:
        importe = liberar_reserva_orden(
            id_portafolio, id_orden, uuid5(id_orden, "liberar-sobrante")
        )
        registrar_paso_saga(
            id_saga, "LIBERAR_SOBRANTE", "COMPLETADO", {"importe": importe}
        )
        cambiar_estado_saga(id_saga, "COMPLETADA")
    except Exception as error:
        # La ejecución ya es válida: no se deshace. Queda pendiente solo
        # devolver el sobrante, que se reintenta con el mismo id_ejecucion.
        registrar_paso_saga(
            id_saga, "LIBERAR_SOBRANTE", "PENDIENTE", {"error": str(error)}
        )
        cambiar_estado_saga(id_saga, "LIBERACION_PENDIENTE")


def ejecutar_orden_compra(
    id_orden: UUID,
    cantidad: Decimal,
    id_ejecucion: UUID = None,
    forzar_falla: str = None,
):
    """Ejecuta una compra total o parcial al precio vigente.

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
    precio_limite = orden["precioLimite"]

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
        if saga["estado"] == "LIBERACION_PENDIENTE":
            _liberar_sobrante(id_saga, id_portafolio, id_orden)
            return obtener_orden(id_orden)
        raise RuntimeError(
            "La ejecución ya tiene una saga pendiente o fallida"
        )

    precio = _precio_ejecucion(simbolo, precio_limite)
    importe = (cantidad * precio).quantize(Decimal("0.01"))

    if importe <= 0:
        raise ValueError("El importe de ejecución debe ser positivo")

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
            "precioLimite": precio_limite,
            "precioVigente": precio,
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

    except Exception:
        _compensar(
            id_saga, id_orden, id_ejecucion, id_portafolio, id_usuario,
            simbolo, fecha, importe, reserva_iniciada, posicion_iniciada,
            historial_iniciado, consumo_iniciado,
        )
        raise

    # 6. Si la orden quedó completa, devolver lo bloqueado de más
    # (se bloqueó al precio límite y se ejecutó a un precio menor o igual).
    orden_actual = obtener_orden(id_orden)
    if orden_actual["estado"] == "EJECUTADA":
        _liberar_sobrante(id_saga, id_portafolio, id_orden)
        return obtener_orden(id_orden)

    cambiar_estado_saga(id_saga, "COMPLETADA")
    return orden_actual


def _compensar(
    id_saga, id_orden, id_ejecucion, id_portafolio, id_usuario, simbolo,
    fecha, importe, reserva_iniciada, posicion_iniciada, historial_iniciado,
    consumo_iniciado,
):
    """Deshace, en orden inverso, los pasos que se llegaron a aplicar."""
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
