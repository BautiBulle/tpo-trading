"""Problema 2: colocación de órdenes de compra con saga compensatoria.

Orden de escritura:
  1. PostgreSQL: bloquear el importe (FOR UPDATE: dos órdenes simultáneas
     del mismo inversor no pueden consumir el mismo saldo).
  2. MongoDB: registrar la orden.
Si falla el paso 2, se libera el saldo bloqueado en el paso 1.

La falla del paso 2 se puede provocar con forzar_falla="ORDEN".
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from app.constantes import cierre_de_mercado

from app.repos.mongo_repo import (
    crear_orden,
    crear_saga,
    cambiar_estado_saga,
    registrar_paso_saga,
    obtener_orden,
    obtener_instrumento,
    obtener_portafolio,
)
from app.repos.precios_redis import get_precio
from app.repos.saldo_pg import bloquear, liberar


def colocar_orden_compra(
    id_portafolio: UUID,
    id_instrumento: UUID,
    cantidad: Decimal,
    precio_limite: Decimal,
    id_orden: UUID = None,
    fecha_expiracion: datetime = None,
    forzar_falla: str = None,
):
    """Coloca una orden de compra reservando fondos mediante una saga.

    Devuelve la orden creada.
    Si falla MongoDB después de bloquear fondos, intenta compensar.

    fecha_expiracion: si no se indica, la orden vence al próximo cierre
    del mercado (las órdenes límite no ejecutadas vencen al cierre).
    forzar_falla: "ORDEN" simula que falla el registro de la orden en
    MongoDB después de bloquear el saldo (para demostrar el rollback).
    """
    if forzar_falla not in (None, "ORDEN"):
        raise ValueError("Escenario de falla desconocido")

    if not isinstance(id_portafolio, UUID):
        raise ValueError("id_portafolio debe ser UUID")

    if not isinstance(id_instrumento, UUID):
        raise ValueError("id_instrumento debe ser UUID")

    if (
        not isinstance(cantidad, Decimal)
        or not cantidad.is_finite()
        or cantidad <= 0
    ):
        raise ValueError("Cantidad inválida")

    if (
        not isinstance(precio_limite, Decimal)
        or not precio_limite.is_finite()
        or precio_limite <= 0
    ):
        raise ValueError("Precio límite inválido")

    if id_orden is None:
        id_orden = uuid4()
    elif not isinstance(id_orden, UUID):
        raise ValueError("id_orden debe ser UUID")

    if fecha_expiracion is None:
        fecha_expiracion = cierre_de_mercado(datetime.now(timezone.utc))
    elif (
        not isinstance(fecha_expiracion, datetime)
        or fecha_expiracion.tzinfo is None
        or fecha_expiracion.utcoffset() is None
    ):
        raise ValueError("fecha_expiracion debe incluir zona horaria")
    elif fecha_expiracion <= datetime.now(timezone.utc):
        raise ValueError("La fecha de expiración ya pasó")

    # Permite reintentar una orden que ya fue registrada.
    existente = obtener_orden(id_orden)
    if existente is not None:
        if (
            existente["idPortafolio"] != str(id_portafolio)
            or existente["idInstrumento"] != str(id_instrumento)
            or existente["tipo"] != "COMPRA"
            or existente["cantidad"] != cantidad
            or existente["precioLimite"] != precio_limite
        ):
            raise ValueError("Orden repetida con datos diferentes")
        return existente

    portafolio = obtener_portafolio(id_portafolio)
    if portafolio is None:
        raise ValueError("El portafolio no existe")

    instrumento = obtener_instrumento(id_instrumento)
    if instrumento is None:
        raise ValueError("El instrumento no existe")

    if instrumento["estado"] != "ACTIVO":
        raise ValueError("El instrumento está suspendido")

    simbolo = instrumento["simbolo"]
    cotizacion = get_precio(simbolo)

    if cotizacion is None:
        raise ValueError("No existe cotización vigente")

    if cotizacion["venta"] > precio_limite:
        raise ValueError(
            "El precio de venta supera el precio límite"
        )

    # Se reserva el máximo que el comprador autorizó.
    importe = (cantidad * precio_limite).quantize(Decimal("0.01"))

    if importe <= 0:
        raise ValueError("Importe de la orden inválido")

    id_saga = uuid4()
    id_bloqueo = uuid4()
    id_liberacion = uuid4()

    crear_saga(
        id_saga,
        "COLOCAR_ORDEN",
        {
            "idOrden": id_orden,
            "idPortafolio": id_portafolio,
            "idInstrumento": id_instrumento,
            "importe": importe,
            "fechaExpiracion": fecha_expiracion,
        },
    )

    fondos_bloqueados = False

    try:
        bloquear(
            id_portafolio,
            importe,
            id_bloqueo,
            id_orden,
        )
        fondos_bloqueados = True

        registrar_paso_saga(
            id_saga,
            "BLOQUEAR_FONDOS",
            "COMPLETADO",
            {"importe": importe},
        )

        if forzar_falla == "ORDEN":
            raise RuntimeError(
                "Falla simulada al registrar la orden en MongoDB"
            )

        crear_orden(
            id_orden,
            id_portafolio,
            id_instrumento,
            "COMPRA",
            cantidad,
            precio_limite,
            fecha_expiracion,
        )

        registrar_paso_saga(
            id_saga,
            "CREAR_ORDEN",
            "COMPLETADO",
            {"idOrden": id_orden},
        )

        cambiar_estado_saga(id_saga, "COMPLETADA")

        return obtener_orden(id_orden)

    except Exception:
        if fondos_bloqueados:
            try:
                # Si la orden ya existe, no liberar la reserva:
                # puede haberse guardado antes del error.
                if obtener_orden(id_orden) is None:
                    liberar(
                        id_portafolio,
                        importe,
                        id_liberacion,
                        id_orden,
                    )
                    registrar_paso_saga(
                        id_saga,
                        "LIBERAR_FONDOS",
                        "COMPENSADO",
                        {"importe": importe},
                    )
                    cambiar_estado_saga(
                        id_saga, "COMPENSADA"
                    )
                else:
                    cambiar_estado_saga(
                        id_saga, "REQUIERE_REVISION"
                    )
            except Exception:
                cambiar_estado_saga(
                    id_saga, "REQUIERE_REVISION"
                )
        else:
            cambiar_estado_saga(id_saga, "FALLIDA")

        raise
