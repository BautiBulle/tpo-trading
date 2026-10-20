"""Repositorio Cassandra: cotizaciones históricas, operaciones y auditoría."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID

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


def registrar_operacion(
    id_operacion: UUID,
    id_usuario: UUID,
    id_instrumento: str,
    fecha_hora: datetime,
    tipo: str,
    cantidad: Decimal,
    precio: Decimal,
) -> None:
    """Registra una operación en las tablas por usuario y por instrumento."""

    if fecha_hora.tzinfo is None:
        raise ValueError("fecha_hora debe incluir zona horaria")

    fecha_hora = fecha_hora.astimezone(timezone.utc)

    if tipo not in ("COMPRA", "VENTA"):
        raise ValueError("El tipo debe ser COMPRA o VENTA")

    if cantidad <= 0 or precio <= 0:
        raise ValueError("La cantidad y el precio deben ser positivos")

    mes = fecha_hora.strftime("%Y-%m")
    dia = fecha_hora.date()
    importe = cantidad * precio

    sesion = get_cassandra()

    insertar_usuario = sesion.prepare("""
        INSERT INTO operaciones_por_usuario (
            id_usuario, mes, fecha_hora, id_operacion,
            id_instrumento, tipo, cantidad, precio, importe
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """)

    insertar_instrumento = sesion.prepare("""
        INSERT INTO operaciones_por_instrumento (
            id_instrumento, dia, fecha_hora, id_operacion,
            id_usuario, tipo, cantidad, precio
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """)

    # Primera escritura: historial consultable por usuario.
    sesion.execute(
        insertar_usuario,
        (
            id_usuario, mes, fecha_hora, id_operacion,
            id_instrumento, tipo, cantidad, precio, importe,
        ),
    )

    # Segunda escritura: historial consultable por instrumento.
    sesion.execute(
        insertar_instrumento,
        (
            id_instrumento, dia, fecha_hora, id_operacion,
            id_usuario, tipo, cantidad, precio,
        ),
    )


def consultar_operaciones_usuario(
    id_usuario: UUID,
    desde: datetime,
    hasta: datetime,
    id_instrumento: str | None = None,
) -> list[dict]:
    """Consulta operaciones de un usuario por período e instrumento opcional."""

    if desde.tzinfo is None or hasta.tzinfo is None:
        raise ValueError("Las fechas deben incluir zona horaria")

    desde = desde.astimezone(timezone.utc)
    hasta = hasta.astimezone(timezone.utc)

    if desde >= hasta:
        raise ValueError("La fecha desde debe ser anterior a hasta")

    sesion = get_cassandra()

    consulta = sesion.prepare("""
        SELECT id_usuario, mes, fecha_hora, id_operacion,
               id_instrumento, tipo, cantidad, precio, importe
        FROM operaciones_por_usuario
        WHERE id_usuario = ?
          AND mes = ?
          AND fecha_hora >= ?
          AND fecha_hora < ?
    """)

    resultados = []
    mes_actual = desde.year * 12 + desde.month - 1
    mes_final = hasta.year * 12 + hasta.month - 1

    while mes_actual <= mes_final:
        anio = mes_actual // 12
        mes = mes_actual % 12 + 1
        mes_texto = f"{anio:04d}-{mes:02d}"

        filas = sesion.execute(
            consulta,
            (id_usuario, mes_texto, desde, hasta),
        )

        for fila in filas:
            if id_instrumento is None or fila.id_instrumento == id_instrumento:
                resultados.append({
                    "id_operacion": fila.id_operacion,
                    "id_usuario": fila.id_usuario,
                    "id_instrumento": fila.id_instrumento,
                    "fecha_hora": fila.fecha_hora,
                    "tipo": fila.tipo,
                    "cantidad": fila.cantidad,
                    "precio": fila.precio,
                    "importe": fila.importe,
                })

        mes_actual += 1

    resultados.sort(key=lambda operacion: operacion["fecha_hora"])

    return resultados


def consultar_operaciones_instrumento(
    id_instrumento: str,
    desde: datetime,
    hasta: datetime,
) -> list[dict]:
    """Consulta operaciones de un instrumento en un rango de fechas."""

    if desde.tzinfo is None or hasta.tzinfo is None:
        raise ValueError("Las fechas deben incluir zona horaria")

    desde = desde.astimezone(timezone.utc)
    hasta = hasta.astimezone(timezone.utc)

    if desde >= hasta:
        raise ValueError("La fecha desde debe ser anterior a hasta")

    sesion = get_cassandra()

    consulta = sesion.prepare("""
        SELECT id_instrumento, fecha_hora, id_operacion,
               id_usuario, tipo, cantidad, precio
        FROM operaciones_por_instrumento
        WHERE id_instrumento = ?
          AND dia = ?
          AND fecha_hora >= ?
          AND fecha_hora < ?
    """)

    resultados = []
    dia_actual = desde.date()

    while dia_actual <= hasta.date():
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
                    "id_operacion": fila.id_operacion,
                    "id_instrumento": fila.id_instrumento,
                    "id_usuario": fila.id_usuario,
                    "fecha_hora": fila.fecha_hora,
                    "tipo": fila.tipo,
                    "cantidad": fila.cantidad,
                    "precio": fila.precio,
                })

        dia_actual += timedelta(days=1)

    resultados.sort(key=lambda operacion: operacion["fecha_hora"])

    return resultados


def registrar_auditoria(
    id_instrumento: str,
    fecha_hora: datetime,
    id_registro: UUID,
    accion: str,
    motivo: str,
    id_operador: UUID,
) -> None:
    """Registra un evento de auditoría de un instrumento."""

    if fecha_hora.tzinfo is None:
        raise ValueError("fecha_hora debe incluir zona horaria")

    fecha_hora = fecha_hora.astimezone(timezone.utc)

    if not id_instrumento.strip():
        raise ValueError("El instrumento es obligatorio")

    if not accion.strip():
        raise ValueError("La acción es obligatoria")

    sesion = get_cassandra()

    consulta = sesion.prepare("""
        INSERT INTO auditoria_por_instrumento (
            id_instrumento, fecha_hora, id_registro,
            accion, motivo, id_operador
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """)

    sesion.execute(
        consulta,
        (
            id_instrumento,
            fecha_hora,
            id_registro,
            accion,
            motivo,
            id_operador,
        ),
    )


def consultar_auditoria(
    id_instrumento: str,
    desde: datetime,
    hasta: datetime,
) -> list[dict]:
    """Consulta eventos de auditoría de un instrumento por período."""

    if desde.tzinfo is None or hasta.tzinfo is None:
        raise ValueError("Las fechas deben incluir zona horaria")

    desde = desde.astimezone(timezone.utc)
    hasta = hasta.astimezone(timezone.utc)

    if desde >= hasta:
        raise ValueError("La fecha desde debe ser anterior a hasta")

    sesion = get_cassandra()

    consulta = sesion.prepare("""
        SELECT id_instrumento, fecha_hora, id_registro,
               accion, motivo, id_operador
        FROM auditoria_por_instrumento
        WHERE id_instrumento = ?
          AND fecha_hora >= ?
          AND fecha_hora < ?
    """)

    filas = sesion.execute(
        consulta,
        (id_instrumento, desde, hasta),
    )

    resultados = []

    for fila in filas:
        resultados.append({
            "id_instrumento": fila.id_instrumento,
            "fecha_hora": fila.fecha_hora,
            "id_registro": fila.id_registro,
            "accion": fila.accion,
            "motivo": fila.motivo,
            "id_operador": fila.id_operador,
        })

    return resultados


def revertir_operacion(
    id_operacion: UUID,
    id_usuario: UUID,
    id_instrumento: str,
    fecha_hora: datetime,
) -> None:
    """Compensa una operación eliminándola de ambos índices de Cassandra.

    Se puede ejecutar más de una vez: DELETE es idempotente.
    La saga debe conservar el registro auditable del rollback.
    """

    if not isinstance(id_operacion, UUID):
        raise ValueError("id_operacion debe ser UUID")

    if not isinstance(id_usuario, UUID):
        raise ValueError("id_usuario debe ser UUID")

    if not isinstance(id_instrumento, str) or not id_instrumento.strip():
        raise ValueError("id_instrumento es obligatorio")

    if not isinstance(fecha_hora, datetime) or fecha_hora.tzinfo is None:
        raise ValueError("fecha_hora debe incluir zona horaria")

    fecha_hora = fecha_hora.astimezone(timezone.utc)

    mes = fecha_hora.strftime("%Y-%m")
    dia = fecha_hora.date()

    sesion = get_cassandra()

    borrar_usuario = sesion.prepare("""
        DELETE FROM operaciones_por_usuario
        WHERE id_usuario = ?
          AND mes = ?
          AND fecha_hora = ?
          AND id_operacion = ?
    """)

    borrar_instrumento = sesion.prepare("""
        DELETE FROM operaciones_por_instrumento
        WHERE id_instrumento = ?
          AND dia = ?
          AND fecha_hora = ?
          AND id_operacion = ?
    """)

    # Se intentan ambas eliminaciones. Repetirlas no duplica efectos.
    errores = []

    try:
        sesion.execute(
            borrar_usuario,
            (id_usuario, mes, fecha_hora, id_operacion),
        )
    except Exception as error:
        errores.append(error)

    try:
        sesion.execute(
            borrar_instrumento,
            (id_instrumento, dia, fecha_hora, id_operacion),
        )
    except Exception as error:
        errores.append(error)

    if errores:
        raise RuntimeError(
            "No se pudo completar la compensación en Cassandra"
        ) from errores[0]
