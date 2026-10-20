"""Carga inicial reproducible para la plataforma de trading.

Ejecutar desde la raíz:
    python -m seed.cargar_datos

Requiere las cuatro bases inicializadas.
"""

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid5, NAMESPACE_DNS

from app.config import get_mongo_db, get_pg

USUARIOS = 1000
INSTRUMENTOS = 120
COTIZACIONES_HISTORICAS = 50000

SECTORES = (
    "TECNOLOGIA",
    "ENERGIA",
    "FINANZAS",
    "SALUD",
    "INDUSTRIA",
    "CONSUMO",
)


def identificador(tipo, numero):
    """UUID determinístico para evitar duplicados."""
    return uuid5(NAMESPACE_DNS, f"trading-seed-{tipo}-{numero}")


def cargar_mongodb():
    """Carga usuarios, instrumentos y portafolios."""
    db = get_mongo_db()

    print("Cargando MongoDB...")

    for numero in range(USUARIOS):
        usuario_id = identificador("usuario", numero)
        portafolio_id = identificador("portafolio", numero)

        db.usuarios.update_one(
            {"_id": str(usuario_id)},
            {
                "$setOnInsert": {
                    "nombre": f"Usuario {numero + 1}",
                    "email": f"usuario{numero + 1}@trading.test",
                    "fechaCreacion": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

        db.portafolios.update_one(
            {"_id": str(portafolio_id)},
            {
                "$setOnInsert": {
                    "idUsuario": str(usuario_id),
                    "posiciones": [],
                    "fechaCreacion": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    for numero in range(INSTRUMENTOS):
        instrumento_id = identificador("instrumento", numero)
        simbolo = f"ACT{numero + 1:03d}"

        db.instrumentos.update_one(
            {"_id": str(instrumento_id)},
            {
                "$setOnInsert": {
                    "simbolo": simbolo,
                    "nombre": f"Empresa {numero + 1}",
                    "sector": SECTORES[numero % len(SECTORES)],
                    "estado": "ACTIVO",
                    "fechaCreacion": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    print("MongoDB: 1000 usuarios, 1000 portafolios y 120 instrumentos.")


def cargar_postgresql():
    """Deposita un saldo inicial por portafolio sin duplicarlo."""
    print("Cargando PostgreSQL...")

    with get_pg() as conexion:
        with conexion.cursor() as cursor:
            for numero in range(USUARIOS):
                portafolio_id = identificador("portafolio", numero)
                operacion_id = identificador("deposito", numero)

                cursor.execute(
                    """
                    INSERT INTO saldo (
                        id_portafolio,
                        saldo_disponible,
                        saldo_bloqueado
                    )
                    VALUES (%s, 0, 0)
                    ON CONFLICT (id_portafolio) DO NOTHING
                    """,
                    (portafolio_id,),
                )

                cursor.execute(
                    """
                    INSERT INTO movimiento_saldo (
                        id_movimiento,
                        id_portafolio,
                        tipo,
                        importe,
                        id_operacion
                    )
                    VALUES (%s, %s, 'DEPOSITO', %s, %s)
                    ON CONFLICT (id_operacion, tipo) DO NOTHING
                    RETURNING id_movimiento
                    """,
                    (
                        identificador("movimiento", numero),
                        portafolio_id,
                        Decimal("100000.00"),
                        operacion_id,
                    ),
                )

                if cursor.fetchone() is not None:
                    cursor.execute(
                        """
                        UPDATE saldo
                        SET saldo_disponible =
                            saldo_disponible + %s
                        WHERE id_portafolio = %s
                        """,
                        (Decimal("100000.00"), portafolio_id),
                    )

    print("PostgreSQL: saldos y depósitos iniciales cargados.")


def cargar_redis():
    """Carga precios iniciales utilizando el repositorio existente."""
    from app.repos.precios_redis import set_precio

    print("Cargando Redis...")

    fecha = datetime.now(timezone.utc)

    for numero in range(INSTRUMENTOS):
        simbolo = f"ACT{numero + 1:03d}"
        base = Decimal(100 + numero)

        set_precio(
            simbolo,
            base - Decimal("0.50"),
            base + Decimal("0.50"),
            base,
            fecha,
        )

    print("Redis: 120 cotizaciones actuales cargadas.")



def cargar_cassandra():
    """Carga 50.000 cotizaciones históricas en Cassandra."""
    from app.config import get_cassandra_session

    print("Cargando Cassandra...")

    sesion = get_cassandra_session()

    consulta = sesion.prepare(
        """
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
        """
    )

    generador = random.Random(42)
    inicio = datetime(2025, 1, 1, tzinfo=timezone.utc)

    for numero in range(COTIZACIONES_HISTORICAS):
        simbolo = f"ACT{numero % INSTRUMENTOS + 1:03d}"
        fecha = inicio + timedelta(minutes=numero)

        precio = Decimal(
            str(round(generador.uniform(50, 500), 2))
        )

        precio_compra = precio - Decimal("0.50")
        precio_venta = precio + Decimal("0.50")
        volumen = generador.randint(100, 10000)

        sesion.execute(
            consulta,
            (
                simbolo,
                fecha.date(),
                fecha,
                precio_compra,
                precio_venta,
                precio,
                volumen,
            ),
        )

        if (numero + 1) % 10000 == 0:
            print(f"  {numero + 1} cotizaciones cargadas")

    print("Cassandra: 50.000 cotizaciones históricas cargadas.")


def main():
    cargar_mongodb()
    cargar_postgresql()
    cargar_redis()
    cargar_cassandra()

    print("Carga inicial finalizada.")
    print("Total previsto: más de 52.000 registros.")


if __name__ == "__main__":
    main()
