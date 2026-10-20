"""Problema 7: concentración sectorial y operaciones potencialmente en espejo.

Consultas de solo lectura sobre MongoDB, Redis y Cassandra.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from app.config import get_mongo_db
from app.repos.historial_cass import consultar_operaciones_instrumento
from app.repos.posiciones_mongo import listar_posiciones_portafolio
from app.repos.precios_redis import get_precio


def _uuid(valor):
    return valor if isinstance(valor, UUID) else UUID(str(valor))


def _fecha(fecha):
    if not isinstance(fecha, datetime) or fecha.tzinfo is None or fecha.utcoffset() is None:
        raise ValueError("Las fechas deben incluir zona horaria")
    return fecha.astimezone(timezone.utc)


def detectar_concentracion_riesgo(umbral_porcentaje=Decimal("50")):
    """Detecta usuarios cuya exposición a un sector supera el umbral.

    El denominador es el valor de sus tenencias (no incluye efectivo).
    """
    umbral = Decimal(str(umbral_porcentaje))
    if not umbral.is_finite() or not Decimal("0") <= umbral <= Decimal("100"):
        raise ValueError("El umbral debe estar entre 0 y 100")

    db = get_mongo_db()
    instrumentos = {str(i["_id"]): i for i in db.instrumentos.find({})}
    cotizaciones = {}
    alertas = []
    inversores_analizados = 0

    for portafolio in db.portafolios.find({}):
        sectores = defaultdict(lambda: Decimal("0"))
        total = Decimal("0")
        for posicion in listar_posiciones_portafolio(_uuid(portafolio["_id"])):
            cantidad = posicion["cantidad"]
            if not isinstance(cantidad, Decimal) or not cantidad.is_finite() or cantidad < 0:
                raise ValueError("Cantidad de posición inválida")
            if cantidad == 0:
                continue
            instrumento = instrumentos.get(str(posicion["idInstrumento"]))
            if instrumento is None:
                raise ValueError("Instrumento de posición inexistente")
            simbolo = instrumento["simbolo"]
            if simbolo not in cotizaciones:
                cotizaciones[simbolo] = get_precio(simbolo)
            cotizacion = cotizaciones[simbolo]
            if cotizacion is None:
                raise ValueError(f"Falta cotización para {simbolo}")
            precio = cotizacion["ultimo"]
            if not isinstance(precio, Decimal) or not precio.is_finite() or precio < 0:
                raise ValueError(f"Precio inválido para {simbolo}")
            valor = cantidad * precio
            sectores[instrumento.get("sector") or "SIN_SECTOR"] += valor
            total += valor

        if total <= 0:
            continue
        inversores_analizados += 1
        for sector, valor in sectores.items():
            porcentaje = valor * Decimal("100") / total
            if porcentaje >= umbral:
                alertas.append({
                    "idUsuario": str(portafolio["idUsuario"]),
                    "idPortafolio": str(portafolio["_id"]),
                    "sector": sector,
                    "valorSector": valor,
                    "valorTenencias": total,
                    "porcentaje": porcentaje,
                })

    alertas.sort(key=lambda a: a["porcentaje"], reverse=True)
    return {"umbralPorcentaje": umbral, "portafoliosConTenencias": inversores_analizados,
            "alertas": alertas}


def detectar_operaciones_espejo(desde, hasta, ventana_segundos=5, minimo_usuarios=2):
    """Detecta grupos de usuarios distintos con operaciones cercanas en tiempo.

    Se agrupan por instrumento y sentido; una operación puede aparecer en
    más de un grupo si hay varias coincidencias en una ventana temporal.
    """
    desde, hasta = _fecha(desde), _fecha(hasta)
    if desde >= hasta:
        raise ValueError("desde debe ser anterior a hasta")
    if not isinstance(ventana_segundos, (int, float)) or not 0 < ventana_segundos <= 3600:
        raise ValueError("ventana_segundos debe estar entre 0 y 3600")
    if not isinstance(minimo_usuarios, int) or minimo_usuarios < 2:
        raise ValueError("minimo_usuarios debe ser al menos 2")

    db = get_mongo_db()
    instrumentos = list(db.instrumentos.find({}, {"_id": 1, "simbolo": 1}))
    alertas = []
    vistos = set()
    ventana = timedelta(seconds=ventana_segundos)

    for instrumento in instrumentos:
        simbolo = instrumento["simbolo"]
        operaciones = consultar_operaciones_instrumento(simbolo, desde, hasta)
        por_tipo = defaultdict(list)
        for op in operaciones:
            if op["tipo"] in ("COMPRA", "VENTA"):
                por_tipo[op["tipo"]].append(op)

        for tipo, eventos in por_tipo.items():
            eventos.sort(key=lambda e: e["fecha_hora"])
            izquierda = 0
            for derecha, actual in enumerate(eventos):
                while eventos[izquierda]["fecha_hora"] < actual["fecha_hora"] - ventana:
                    izquierda += 1
                grupo = eventos[izquierda:derecha + 1]
                usuarios = {str(op["id_usuario"]) for op in grupo}
                if len(usuarios) < minimo_usuarios:
                    continue
                ids = tuple(sorted(str(op["id_operacion"]) for op in grupo))
                clave = (simbolo, tipo, ids)
                if clave in vistos:
                    continue
                vistos.add(clave)
                alertas.append({
                    "simbolo": simbolo,
                    "tipo": tipo,
                    "desde": grupo[0]["fecha_hora"],
                    "hasta": actual["fecha_hora"],
                    "usuarios": sorted(usuarios),
                    "operaciones": [{
                        "idOperacion": str(op["id_operacion"]),
                        "idUsuario": str(op["id_usuario"]),
                        "fechaHora": op["fecha_hora"],
                        "cantidad": op["cantidad"],
                        "precio": op["precio"],
                    } for op in grupo],
                })

    alertas.sort(key=lambda a: (a["desde"], a["simbolo"]))
    return {"ventanaSegundos": ventana_segundos, "minimoUsuarios": minimo_usuarios,
            "instrumentosAnalizados": len(instrumentos), "alertas": alertas}
