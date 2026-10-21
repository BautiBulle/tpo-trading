"""Problema 5: valor actual del portafolio y rendimiento diario.

MongoDB: posiciones e instrumentos.
Redis: cotizaciones vigentes.
Cassandra: cotizaciones históricas de referencia.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from app.repos.mongo_repo import obtener_portafolio, obtener_instrumento
from app.repos.posiciones_mongo import listar_posiciones_portafolio
from app.repos.precios_redis import get_precio
from app.repos.historial_cass import consultar_precios


def obtener_referencia_diaria(simbolo, inicio_dia):
    """Busca el último precio anterior al inicio del día UTC.

    Se consultan hasta siete días anteriores para contemplar
    fines de semana y días sin cotizaciones.
    """
    desde = inicio_dia - timedelta(days=7)

    historico = consultar_precios(
        simbolo,
        desde,
        inicio_dia,
    )

    if not historico:
        return None

    referencia = historico[-1]
    precio = referencia["precio_ultimo"]

    if (
        not isinstance(precio, Decimal)
        or not precio.is_finite()
        or precio <= 0
    ):
        raise ValueError(
            f"Precio histórico inválido para {simbolo}"
        )

    return {
        "precio": precio,
        "fecha": referencia["fecha_hora"],
    }


def calcular_valor_portafolio(id_portafolio: UUID):
    """Valúa las posiciones y calcula rendimiento diario por instrumento.

    El valor total incluye solo tenencias, no efectivo de PostgreSQL.
    El rendimiento diario compara el precio vigente con la última
    cotización anterior al día UTC de la consulta.

    Si no existe referencia histórica, el rendimiento es None.
    Esta función es de solo lectura.
    """
    if not isinstance(id_portafolio, UUID):
        raise ValueError("id_portafolio debe ser UUID")

    portafolio = obtener_portafolio(id_portafolio)
    if portafolio is None:
        raise ValueError("El portafolio no existe")

    fecha_consulta = datetime.now(timezone.utc)
    inicio_dia = fecha_consulta.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

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
            raise ValueError(
                "La posición tiene una cantidad inválida"
            )

        if cantidad == 0:
            continue

        id_instrumento = UUID(posicion["idInstrumento"])
        instrumento = obtener_instrumento(id_instrumento)

        if instrumento is None:
            raise ValueError(
                f"El instrumento {id_instrumento} no existe"
            )

        simbolo = instrumento["simbolo"]
        cotizacion = get_precio(simbolo)

        if cotizacion is None:
            raise ValueError(
                f"No existe cotización vigente para {simbolo}"
            )

        precio = cotizacion["ultimo"]

        if (
            not isinstance(precio, Decimal)
            or not precio.is_finite()
            or precio < 0
        ):
            raise ValueError(
                f"La cotización de {simbolo} tiene un precio inválido"
            )

        valor_actual = cantidad * precio
        valor_total += valor_actual

        referencia = obtener_referencia_diaria(
            simbolo,
            inicio_dia,
        )

        precio_referencia = None
        fecha_referencia = None
        rendimiento_diario = None

        if referencia is not None:
            precio_referencia = referencia["precio"]
            fecha_referencia = referencia["fecha"]

            rendimiento_diario = (
                (precio - precio_referencia)
                / precio_referencia
                * Decimal("100")
            )

        detalle.append({
            "idInstrumento": str(id_instrumento),
            "simbolo": simbolo,
            "cantidad": cantidad,
            "precioActual": precio,
            "valorActual": valor_actual,
            "fechaCotizacion": cotizacion["fechaHora"],
            "precioReferenciaDiaria": precio_referencia,
            "fechaReferenciaDiaria": fecha_referencia,
            "rendimientoDiarioPorcentaje": rendimiento_diario,
        })

    return {
        "idPortafolio": str(id_portafolio),
        "valorTotal": valor_total,
        "posiciones": detalle,
        "fechaConsulta": fecha_consulta,
    }
