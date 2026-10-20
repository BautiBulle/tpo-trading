"""Problema 6: historial y rendimiento usando MongoDB y Cassandra."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from app.repos.mongo_repo import obtener_usuario, obtener_instrumento
from app.repos.historial_cass import consultar_operaciones_usuario


def consultar_historial(
    id_usuario: UUID,
    desde: datetime,
    hasta: datetime,
    id_instrumento: UUID = None,
):
    """Devuelve las operaciones del usuario entre desde (incluido) y hasta.

    El instrumento es opcional. MongoDB resuelve su UUID al símbolo que el
    P3 guarda en Cassandra. Se incluyen instrumentos suspendidos.
    """
    desde = _fecha_utc(desde, "desde")
    hasta = _fecha_utc(hasta, "hasta")
    if desde >= hasta:
        raise ValueError("La fecha desde debe ser anterior a hasta")

    _, simbolo = _obtener_contexto(id_usuario, id_instrumento)
    return _leer_operaciones(id_usuario, desde, hasta, simbolo)


def calcular_rendimiento_12_meses(
    id_usuario: UUID,
    fecha_actual: datetime = None,
    id_instrumento: UUID = None,
):
    """Calcula ganancia realizada y porcentaje sobre el costo vendido.

    Usa costo promedio ponderado y los últimos doce meses calendario.
    Las compras y ventas anteriores reconstruyen el costo de las tenencias,
    pero solo las ventas del período aportan al rendimiento. No valúa las
    posiciones abiertas ni incluye comisiones, impuestos o dividendos.
    """
    if fecha_actual is None:
        fecha_actual = datetime.now(timezone.utc)
    hasta = _fecha_utc(fecha_actual, "fecha_actual")
    if hasta.year == 1:
        raise ValueError("fecha_actual debe permitir consultar doce meses anteriores")
    try:
        desde = hasta.replace(year=hasta.year - 1)
    except ValueError:
        # El 29 de febrero no existe en el año anterior.
        desde = hasta.replace(year=hasta.year - 1, day=28)

    usuario, simbolo = _obtener_contexto(id_usuario, id_instrumento)
    inicio_historial = _fecha_utc(usuario["fechaCreacion"], "fechaCreacion del usuario")
    operaciones = []
    if inicio_historial < hasta:
        operaciones = _leer_operaciones(id_usuario, inicio_historial, hasta, simbolo)

    posiciones = {}
    por_instrumento = {}
    cantidad_operaciones = 0

    for operacion in operaciones:
        simbolo_operacion = operacion["simbolo"]
        if simbolo_operacion not in posiciones:
            posiciones[simbolo_operacion] = {
                "cantidad": Decimal("0"), "costo": Decimal("0"),
                "ultimaFecha": None, "ultimoTipo": None,
            }
        posicion = posiciones[simbolo_operacion]
        costo_vendido = _actualizar_costo(posicion, operacion)

        if operacion["fechaHora"] < desde:
            continue

        cantidad_operaciones += 1
        if simbolo_operacion not in por_instrumento:
            por_instrumento[simbolo_operacion] = {
                "simbolo": simbolo_operacion,
                "importeCompras": Decimal("0"),
                "importeVentas": Decimal("0"),
                "costoVendido": Decimal("0"),
            }
        resumen = por_instrumento[simbolo_operacion]
        importe = operacion["cantidad"] * operacion["precio"]
        if operacion["tipo"] == "COMPRA":
            resumen["importeCompras"] += importe
        else:
            resumen["importeVentas"] += importe
            resumen["costoVendido"] += costo_vendido

    totales = {
        "importeCompras": Decimal("0"), "importeVentas": Decimal("0"),
        "costoVendido": Decimal("0"),
    }
    detalle = []
    for simbolo_operacion in sorted(por_instrumento):
        resumen = por_instrumento[simbolo_operacion]
        for campo in totales:
            totales[campo] += resumen[campo]
        _agregar_rendimiento(resumen)
        detalle.append(resumen)
    _agregar_rendimiento(totales)

    return {
        "idUsuario": str(id_usuario),
        "idInstrumento": str(id_instrumento) if id_instrumento else None,
        "desde": desde, "hasta": hasta,
        "metodo": "COSTO_PROMEDIO_PONDERADO",
        "cantidadOperaciones": cantidad_operaciones,
        **totales,
        "instrumentos": detalle,
    }


def _actualizar_costo(posicion, operacion):
    """Reconstruye la tenencia y devuelve el costo de una venta, si la hay."""
    cantidad = operacion["cantidad"]
    precio = operacion["precio"]
    tipo = operacion["tipo"]
    if tipo not in ("COMPRA", "VENTA"):
        raise ValueError("El historial contiene un tipo de operación inválido")
    for nombre, valor in (("cantidad", cantidad), ("precio", precio)):
        if not isinstance(valor, Decimal) or not valor.is_finite() or valor <= 0:
            raise ValueError(f"El historial contiene {nombre} inválido")
    if (
        posicion["ultimaFecha"] == operacion["fechaHora"]
        and posicion["ultimoTipo"] != tipo
    ):
        # UUID no indica cuál ocurrió primero; no inventar un costo promedio.
        raise ValueError("Compra y venta simultáneas: no se puede determinar su orden")
    posicion["ultimaFecha"] = operacion["fechaHora"]
    posicion["ultimoTipo"] = tipo

    if tipo == "COMPRA":
        posicion["cantidad"] += cantidad
        posicion["costo"] += cantidad * precio
        return Decimal("0")

    if cantidad > posicion["cantidad"]:
        raise ValueError(
            f"Historial incompleto para {operacion['simbolo']}: "
            "venta sin compras suficientes"
        )
    # Una venta total consume el costo exacto y no deja residuos decimales.
    costo = posicion["costo"]
    if cantidad < posicion["cantidad"]:
        costo = costo * cantidad / posicion["cantidad"]
    posicion["cantidad"] -= cantidad
    posicion["costo"] -= costo
    return costo


def _agregar_rendimiento(resumen):
    ganancia = resumen["importeVentas"] - resumen["costoVendido"]
    resumen["gananciaRealizada"] = ganancia
    resumen["rendimientoPorcentual"] = (
        ganancia * Decimal("100") / resumen["costoVendido"]
        if resumen["costoVendido"] > 0 else None
    )


def _fecha_utc(fecha, nombre):
    if (
        not isinstance(fecha, datetime)
        or fecha.tzinfo is None
        or fecha.utcoffset() is None
    ):
        raise ValueError(f"{nombre} debe incluir zona horaria")
    return fecha.astimezone(timezone.utc)


def _obtener_contexto(id_usuario, id_instrumento):
    if not isinstance(id_usuario, UUID):
        raise ValueError("id_usuario debe ser UUID")
    if id_instrumento is not None and not isinstance(id_instrumento, UUID):
        raise ValueError("id_instrumento debe ser UUID")

    usuario = obtener_usuario(id_usuario)
    if usuario is None:
        raise ValueError("El usuario no existe")

    simbolo = None
    if id_instrumento is not None:
        instrumento = obtener_instrumento(id_instrumento)
        if instrumento is None:
            raise ValueError("El instrumento no existe")
        simbolo = instrumento["simbolo"]
    return usuario, simbolo


def _leer_operaciones(id_usuario, desde, hasta, simbolo):
    registros = consultar_operaciones_usuario(id_usuario, desde, hasta, simbolo)
    operaciones = []
    for registro in registros:
        fecha = registro["fecha_hora"]
        # El driver de Cassandra devuelve timestamps sin tzinfo, en UTC.
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)
        operaciones.append({
            "idOperacion": str(registro["id_operacion"]),
            "idUsuario": str(registro["id_usuario"]),
            "simbolo": registro["id_instrumento"],
            "fechaHora": fecha.astimezone(timezone.utc),
            "tipo": registro["tipo"],
            "cantidad": registro["cantidad"],
            "precio": registro["precio"],
            "importe": registro["importe"],
        })
    operaciones.sort(key=lambda operacion: (
        operacion["fechaHora"], operacion["idOperacion"]
    ))
    return operaciones
