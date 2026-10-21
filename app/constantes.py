"""Convenciones acordadas: estados de la orden como constantes."""

PENDIENTE = "PENDIENTE"
PARCIAL = "PARCIAL"
EN_CANCELACION = "EN_CANCELACION"
PARCIALMENTE_EJECUTADA = "PARCIALMENTE_EJECUTADA"
EJECUTADA = "EJECUTADA"
CANCELADA = "CANCELADA"
VENCIDA = "VENCIDA"
RECHAZADA = "RECHAZADA"

# Cierre del mercado: las órdenes límite no ejecutadas vencen a esta hora (UTC).
# 20:00 UTC = 17:00 de Buenos Aires, horario de cierre de BYMA.
HORA_CIERRE_MERCADO_UTC = 20


def cierre_de_mercado(fecha):
    """Devuelve el próximo cierre de mercado posterior a `fecha` (UTC)."""
    from datetime import timedelta, timezone

    fecha = fecha.astimezone(timezone.utc)
    cierre = fecha.replace(
        hour=HORA_CIERRE_MERCADO_UTC, minute=0, second=0, microsecond=0
    )
    if cierre <= fecha:
        cierre += timedelta(days=1)
    return cierre
