"""Repositorio Redis: almacenamiento y consulta de cotizaciones vigentes."""

from datetime import datetime, timezone
from decimal import Decimal

from app.config import get_redis


# La comparación y la escritura ocurren en una única operación atómica.
# Se utiliza un campo adicional interno para ordenar las actualizaciones.
_SCRIPT_ACTUALIZAR_PRECIO = """
local anterior = redis.call('HGET', KEYS[1], 'timestamp_ns')

if anterior and string.len(anterior) == string.len(ARGV[1])
    and anterior >= ARGV[1] then
    return 0
end

redis.call(
    'HSET', KEYS[1],
    'compra', ARGV[2],
    'venta', ARGV[3],
    'ultimo', ARGV[4],
    'fechaHora', ARGV[5],
    'timestamp_ns', ARGV[1]
)

return 1
"""


def set_precio(
    simbolo: str,
    compra: Decimal,
    venta: Decimal,
    ultimo: Decimal,
    fecha_hora: datetime,
) -> None:
    """Guarda la cotización solo si es más reciente que la vigente."""

    if not isinstance(simbolo, str) or not simbolo.strip():
        raise ValueError("El símbolo del instrumento no puede estar vacío")

    if not isinstance(fecha_hora, datetime):
        raise ValueError("fecha_hora debe ser datetime")

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

    # Representación ordenable con precisión de microsegundos.
    # El prefijo fijo permite comparar timestamps como cadenas.
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    diferencia = fecha_utc - epoch
    timestamp_us = (
        (diferencia.days * 86400 + diferencia.seconds) * 1_000_000
        + diferencia.microseconds
    )

    # Offset para mantener el formato positivo y de ancho fijo.
    timestamp_ordenable = f"{timestamp_us + 10**19:020d}"

    clave = f"precio:{simbolo.strip()}"

    cliente = get_redis()
    cliente.eval(
        _SCRIPT_ACTUALIZAR_PRECIO,
        1,
        clave,
        timestamp_ordenable,
        str(compra),
        str(venta),
        str(ultimo),
        fecha_utc.isoformat(),
    )


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
