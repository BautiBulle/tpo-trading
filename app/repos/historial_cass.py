"""Repositorio Cassandra: cotizaciones históricas, operaciones y auditoría."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.config import get_cassandra


def registrar_precio(
    id_instrumento: str,
    fecha_hora: datetime,
    precio_compra: Decimal,
    precio_venta: Decimal,
    precio_ultimo: Decimal,
    volumen: int,
) -> None:
    """Registra una cotización histórica de un instrumento en Cassandra."""

    # Trabajamos con fechas en UTC, como acordamos para el TP.
    if fecha_hora.tzinfo is None:
        raise ValueError("fecha_hora debe incluir zona horaria")

    fecha_hora = fecha_hora.astimezone(timezone.utc)
    dia = fecha_hora.date()

    # Obtenemos la sesión reutilizable definida en config.py.
    sesion = get_cassandra()

    # Preparamos el INSERT con parámetros para evitar concatenar valores.
    consulta = sesion.prepare("""
        INSERT INTO historico_cotizacion (
            id_instrumento,
            dia,
            fecha_hora,
            precio_compra,
            precio_venta,
            precio_ultimo,
            volumen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """)

    # Ejecutamos la escritura.
    sesion.execute(
        consulta,
        (
            id_instrumento,
            dia,
            fecha_hora,
            precio_compra,
            precio_venta,
            precio_ultimo,
            volumen,
        ),
    )
    

def consultar_precios(
    id_instrumento: str,
    desde: datetime,
    hasta: datetime,
) -> list[dict]:
    """Consulta cotizaciones históricas entre dos fechas, ordenadas de menor a mayor."""

    if desde.tzinfo is None or hasta.tzinfo is None:
        raise ValueError("Las fechas deben incluir zona horaria")

    desde = desde.astimezone(timezone.utc)
    hasta = hasta.astimezone(timezone.utc)

    if desde >= hasta:
        raise ValueError("La fecha desde debe ser anterior a hasta")

    sesion = get_cassandra()

    consulta = sesion.prepare("""
        SELECT id_instrumento, fecha_hora,
               precio_compra, precio_venta,
               precio_ultimo, volumen
        FROM historico_cotizacion
        WHERE id_instrumento = ?
          AND dia = ?
          AND fecha_hora >= ?
          AND fecha_hora < ?
    """)

    resultados = []
    dia_actual = desde.date()

    while dia_actual <= hasta.date():
        # Limitamos la búsqueda al intervalo correspondiente a este día.
        inicio_dia = datetime.combine(
            dia_actual, datetime.min.time(), tzinfo=timezone.utc
        )
        fin_dia = inicio_dia + timedelta(days=1)

        inicio = max(desde, inicio_dia)
        fin = min(hasta, fin_dia)

        if inicio < fin:
            filas = sesion.execute(
                consulta,
                (id_instrumento, dia_actual, inicio, fin),
            )

            for fila in filas:
                resultados.append({
                    "id_instrumento": fila.id_instrumento,
                    "fecha_hora": fila.fecha_hora,
                    "precio_compra": fila.precio_compra,
                    "precio_venta": fila.precio_venta,
                    "precio_ultimo": fila.precio_ultimo,
                    "volumen": fila.volumen,
                })

        dia_actual += timedelta(days=1)

    resultados.sort(key=lambda registro: registro["fecha_hora"])

    return resultados

