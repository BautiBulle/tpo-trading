"""Repositorio Redis: almacenamiento y consulta de cotizaciones vigentes."""

from datetime import datetime, timezone
from decimal import Decimal

from app.config import get_redis


def set_precio(
    simbolo: str,
    compra: Decimal,
    venta: Decimal,
    ultimo: Decimal,
    fecha_hora: datetime,
) -> None:
    """Guarda la cotización vigente de un instrumento financiero."""

    if not isinstance(simbolo, str) or not simbolo.strip():
        raise ValueError("El símbolo del instrumento no puede estar vacío")

    if fecha_hora.tzinfo is None or fecha_hora.utcoffset() is None:
        raise ValueError("fecha_hora debe incluir zona horaria")

    for nombre, valor in (
        ("compra", compra),
        ("venta", venta),
        ("ultimo", ultimo),
    ):
        if not isinstance(valor, Decimal):
            raise ValueError(f"{nombre} debe ser Decimal")
        if not valor.is_finite() or valor < 0:
            raise ValueError(f"{nombre} debe ser un precio válido no negativo")

    fecha_utc = fecha_hora.astimezone(timezone.utc)

    clave = f"precio:{simbolo.strip()}"

    datos = {
        "compra": str(compra),
        "venta": str(venta),
        "ultimo": str(ultimo),
        "fechaHora": fecha_utc.isoformat(),
    }

    cliente = get_redis()
    cliente.hset(clave, mapping=datos)


def get_precio(simbolo: str) -> dict | None:
    """Devuelve la cotización vigente o None si no existe."""

    if not isinstance(simbolo, str) or not simbolo.strip():
        raise ValueError("El símbolo del instrumento no puede estar vacío")

    cliente = get_redis()
    datos = cliente.hgetall(f"precio:{simbolo.strip()}")

    if not datos:
        return None

    return {
        "compra": Decimal(datos["compra"]),
        "venta": Decimal(datos["venta"]),
        "ultimo": Decimal(datos["ultimo"]),
        "fechaHora": datetime.fromisoformat(datos["fechaHora"]),
    }
