"""Repositorio PostgreSQL: saldos y movimientos financieros ACID."""

from decimal import Decimal
from uuid import UUID, uuid4

from app.config import get_pg


def _validar_importe(importe):
    """Valida importes monetarios con dos decimales."""
    if not isinstance(importe, Decimal):
        raise ValueError("El importe debe ser Decimal")

    if not importe.is_finite() or importe <= 0:
        raise ValueError("El importe debe ser positivo y finito")

    if importe.as_tuple().exponent < -2:
        raise ValueError("El importe admite como máximo dos decimales")


def _validar_uuid(valor, nombre):
    if not isinstance(valor, UUID):
        raise ValueError(f"{nombre} debe ser UUID")


def _registrar_movimiento(
    cur, id_portafolio, tipo, importe, id_operacion, id_orden
):
    """Registra un movimiento dentro de la transacción activa."""
    cur.execute(
        """
        INSERT INTO movimiento_saldo (
            id_movimiento, id_portafolio, tipo,
            importe, id_orden, id_operacion
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(), id_portafolio, tipo,
            importe, id_orden, id_operacion,
        ),
    )


def _ejecutar_movimiento(
    id_portafolio,
    tipo,
    importe,
    id_operacion,
    id_orden=None,
):
    """Ejecuta un movimiento con bloqueo de fila e idempotencia."""

    _validar_uuid(id_portafolio, "id_portafolio")
    _validar_uuid(id_operacion, "id_operacion")
    _validar_importe(importe)

    if id_orden is not None:
        _validar_uuid(id_orden, "id_orden")

    conexion = get_pg()

    try:
        with conexion.transaction():
            with conexion.cursor() as cur:

                # Crea el saldo si todavía no existe.
                cur.execute(
                    """
                    INSERT INTO saldo (
                        id_portafolio,
                        saldo_disponible,
                        saldo_bloqueado
                    )
                    VALUES (%s, 0, 0)
                    ON CONFLICT (id_portafolio) DO NOTHING
                    """,
                    (id_portafolio,),
                )

                # Bloquea la fila para evitar modificaciones simultáneas.
                cur.execute(
                    """
                    SELECT saldo_disponible, saldo_bloqueado
                    FROM saldo
                    WHERE id_portafolio = %s
                    FOR UPDATE
                    """,
                    (id_portafolio,),
                )

                disponible, bloqueado = cur.fetchone()

                # Verifica si el paso de la saga ya se ejecutó.
                cur.execute(
                    """
                    SELECT importe, id_portafolio, id_orden
                    FROM movimiento_saldo
                    WHERE id_operacion = %s AND tipo = %s
                    """,
                    (id_operacion, tipo),
                )

                anterior = cur.fetchone()

                if anterior is not None:
                    imp_ant, port_ant, orden_ant = anterior

                    if (
                        imp_ant != importe
                        or port_ant != id_portafolio
                        or orden_ant != id_orden
                    ):
                        raise ValueError(
                            "Operación repetida con datos diferentes"
                        )

                    return False

                if tipo == "DEPOSITO":
                    disponible += importe

                elif tipo == "RETIRO":
                    if disponible < importe:
                        raise ValueError("Saldo disponible insuficiente")
                    disponible -= importe

                elif tipo == "BLOQUEO":
                    if disponible < importe:
                        raise ValueError("Saldo disponible insuficiente")
                    disponible -= importe
                    bloqueado += importe

                elif tipo == "LIBERACION":
                    if bloqueado < importe:
                        raise ValueError("Saldo bloqueado insuficiente")
                    bloqueado -= importe
                    disponible += importe

                elif tipo == "CONSUMO":
                    if bloqueado < importe:
                        raise ValueError("Saldo bloqueado insuficiente")
                    bloqueado -= importe

                else:
                    raise ValueError("Tipo de movimiento desconocido")

                cur.execute(
                    """
                    UPDATE saldo
                    SET saldo_disponible = %s,
                        saldo_bloqueado = %s
                    WHERE id_portafolio = %s
                    """,
                    (disponible, bloqueado, id_portafolio),
                )

                _registrar_movimiento(
                    cur, id_portafolio, tipo,
                    importe, id_operacion, id_orden,
                )

        return True

    except Exception:
        conexion.rollback()
        raise


def depositar(id_portafolio, importe, id_operacion):
    """Aumenta el saldo disponible."""
    return _ejecutar_movimiento(
        id_portafolio, "DEPOSITO", importe, id_operacion
    )


def retirar(id_portafolio, importe, id_operacion):
    """Retira dinero del saldo disponible."""
    return _ejecutar_movimiento(
        id_portafolio, "RETIRO", importe, id_operacion
    )


def bloquear(id_portafolio, importe, id_operacion, id_orden):
    """Reserva fondos para una orden de compra."""
    return _ejecutar_movimiento(
        id_portafolio, "BLOQUEO", importe, id_operacion, id_orden
    )


def liberar(id_portafolio, importe, id_operacion, id_orden):
    """Devuelve fondos bloqueados al saldo disponible."""
    return _ejecutar_movimiento(
        id_portafolio, "LIBERACION", importe, id_operacion, id_orden
    )


def consumir(id_portafolio, importe, id_operacion, id_orden):
    """Consume definitivamente fondos reservados."""
    return _ejecutar_movimiento(
        id_portafolio, "CONSUMO", importe, id_operacion, id_orden
    )


def consultar_saldo(id_portafolio):
    """Consulta el saldo disponible y bloqueado."""
    _validar_uuid(id_portafolio, "id_portafolio")

    conexion = get_pg()

    try:
        with conexion.transaction():
            with conexion.cursor() as cur:
                cur.execute(
                    """
                    SELECT saldo_disponible, saldo_bloqueado
                    FROM saldo
                    WHERE id_portafolio = %s
                    """,
                    (id_portafolio,),
                )
                resultado = cur.fetchone()

        if resultado is None:
            return None

        return {
            "disponible": resultado[0],
            "bloqueado": resultado[1],
        }

    except Exception:
        conexion.rollback()
        raise

