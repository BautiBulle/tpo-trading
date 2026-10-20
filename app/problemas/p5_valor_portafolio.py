"""Problema 5: valor actual de las posiciones usando MongoDB y Redis."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.repos.mongo_repo import obtener_portafolio, obtener_instrumento
from app.repos.posiciones_mongo import listar_posiciones_portafolio
from app.repos.precios_redis import get_precio


def calcular_valor_portafolio(id_portafolio: UUID):
    """Devuelve el valor total y el detalle de las posiciones del portafolio.

    Se utiliza el último precio de Redis, no el precio promedio de compra.
    Es una consulta: no modifica posiciones, saldos ni cotizaciones.
    El total corresponde a las tenencias, sin sumar el efectivo de PostgreSQL.
    """
    if not isinstance(id_portafolio, UUID):
        raise ValueError("id_portafolio debe ser UUID")

    portafolio = obtener_portafolio(id_portafolio)
    if portafolio is None:
        raise ValueError("El portafolio no existe")

    posiciones = listar_posiciones_portafolio(id_portafolio)
    detalle = []
    valor_total = Decimal("0.00")

    for posicion in posiciones:
        cantidad = posicion["cantidad"]
        if (
            not isinstance(cantidad, Decimal)
            or not cantidad.is_finite()
            or cantidad < 0
        ):
            raise ValueError("La posición tiene una cantidad inválida")

        # El rollback del P3 puede conservar una posición con cantidad cero.
        if cantidad == 0:
            continue

        id_instrumento = UUID(posicion["idInstrumento"])
        instrumento = obtener_instrumento(id_instrumento)
        if instrumento is None:
            raise ValueError(f"El instrumento {id_instrumento} no existe")

        simbolo = instrumento["simbolo"]
        cotizacion = get_precio(simbolo)
        if cotizacion is None:
            raise ValueError(f"No existe cotización vigente para {simbolo}")

        precio = cotizacion["ultimo"]
        if (
            not isinstance(precio, Decimal)
            or not precio.is_finite()
            or precio < 0
        ):
            raise ValueError(f"La cotización de {simbolo} tiene un precio inválido")

        # Conservamos los decimales de las cantidades fraccionarias.
        valor_actual = cantidad * precio
        valor_total += valor_actual
        detalle.append({
            "idInstrumento": str(id_instrumento),
            "simbolo": simbolo,
            "cantidad": cantidad,
            "precioActual": precio,
            "valorActual": valor_actual,
            "fechaCotizacion": cotizacion["fechaHora"],
        })

    return {
        "idPortafolio": str(id_portafolio),
        "valorTotal": valor_total,
        "posiciones": detalle,
        "fechaConsulta": datetime.now(timezone.utc),
    }
