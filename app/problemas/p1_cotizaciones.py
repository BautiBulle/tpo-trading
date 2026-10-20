"""Problema 1: publicación continua de cotizaciones.

Redis conserva el último precio de cada instrumento.
Cassandra conserva el historial de cotizaciones.
"""

import argparse
import random
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.repos.precios_redis import get_precio, set_precio
from app.repos.historial_cass import registrar_precio


def redondear_precio(valor):
    return Decimal(str(valor)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def publicar_cotizacion(simbolo, compra, venta, ultimo):
    """Publica una cotización en Redis y Cassandra."""

    compra = redondear_precio(compra)
    venta = redondear_precio(venta)
    ultimo = redondear_precio(ultimo)

    if min(compra, venta, ultimo) <= 0:
        raise ValueError("Los precios deben ser positivos")

    if compra > venta:
        raise ValueError(
            "El precio de compra no puede superar al de venta"
        )

    fecha = datetime.now(timezone.utc)

    # Primero persistimos el historial.
    registrar_precio(
        simbolo,
        fecha,
        compra,
        venta,
        ultimo,
        Decimal("100"),
    )


    # Después actualizamos el precio vigente.
    set_precio(
        simbolo,
        compra,
        venta,
        ultimo,
        fecha,
    )

    return {
        "simbolo": simbolo,
        "compra": compra,
        "venta": venta,
        "ultimo": ultimo,
        "fechaHora": fecha,
    }


def simular_cotizacion(simbolo):
    """Genera una variación pequeña sobre el último precio."""

    actual = get_precio(simbolo)

    if actual is None:
        raise ValueError(
            f"No hay cotización inicial para {simbolo}"
        )

    precio_anterior = actual["ultimo"]

    variacion = Decimal(
        str(random.uniform(-0.003, 0.003))
    )

    nuevo_ultimo = redondear_precio(
        precio_anterior * (Decimal("1") + variacion)
    )

    nuevo_ultimo = max(nuevo_ultimo, Decimal("0.02"))

    compra = redondear_precio(
        nuevo_ultimo * Decimal("0.999")
    )
    venta = redondear_precio(
        nuevo_ultimo * Decimal("1.001")
    )

    compra = max(compra, Decimal("0.01"))
    venta = max(venta, compra)

    return publicar_cotizacion(
        simbolo,
        compra,
        venta,
        nuevo_ultimo,
    )


def ejecutar_publicador(
    cantidad_instrumentos=120,
    rondas=5,
    pausa=0.1,
):
    """Actualiza todos los instrumentos en cada ronda."""

    if not 100 <= cantidad_instrumentos <= 120:
        raise ValueError(
            "La cantidad de instrumentos debe estar entre 100 y 120"
        )

    if rondas <= 0:
        raise ValueError("Las rondas deben ser positivas")

    if pausa < 0:
        raise ValueError("La pausa no puede ser negativa")

    simbolos = [
        f"ACT{numero:03d}"
        for numero in range(1, cantidad_instrumentos + 1)
    ]

    total = 0
    inicio = time.monotonic()

    for ronda in range(1, rondas + 1):
        for simbolo in simbolos:
            simular_cotizacion(simbolo)
            total += 1

        print(
            f"Ronda {ronda}/{rondas}: "
            f"{cantidad_instrumentos} instrumentos actualizados"
        )

        if ronda < rondas and pausa > 0:
            time.sleep(pausa)

    duracion = time.monotonic() - inicio
    velocidad = total / duracion if duracion > 0 else 0

    print(f"Total de cotizaciones: {total}")
    print(f"Duración: {duracion:.2f} segundos")
    print(f"Velocidad: {velocidad:.2f} actualizaciones/segundo")

    return total


def main():
    parser = argparse.ArgumentParser(
        description="Publicador de cotizaciones del Problema 1"
    )

    parser.add_argument(
        "--instrumentos",
        type=int,
        default=120,
    )
    parser.add_argument(
        "--rondas",
        type=int,
        default=5,
    )
    parser.add_argument(
        "--pausa",
        type=float,
        default=0.1,
    )

    args = parser.parse_args()

    ejecutar_publicador(
        cantidad_instrumentos=args.instrumentos,
        rondas=args.rondas,
        pausa=args.pausa,
    )


if __name__ == "__main__":
    main()
