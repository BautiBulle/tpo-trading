"""Repositorio Cassandra: cotizaciones históricas, operaciones y auditoría."""

from datetime import datetime, timezone
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
