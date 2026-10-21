"""Menú de consola para ejecutar los ocho problemas del TPO Trading.

Uso: python -m app.main
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pprint import pprint
from uuid import UUID, uuid4


def _texto(mensaje, defecto=None):
    sufijo = f" [{defecto}]" if defecto is not None else ""
    valor = input(f"{mensaje}{sufijo}: ").strip()
    return valor if valor else defecto


def _uuid(mensaje, opcional=False):
    valor = _texto(mensaje)
    if opcional and not valor:
        return None
    return UUID(valor)


def _decimal(mensaje, defecto=None):
    valor = _texto(mensaje, defecto)
    if valor is None:
        raise ValueError("El valor es obligatorio")
    numero = Decimal(str(valor).replace(",", "."))
    if not numero.is_finite():
        raise ValueError("El número debe ser finito")
    return numero


def _entero(mensaje, defecto=None):
    valor = _texto(mensaje, defecto)
    if valor is None:
        raise ValueError("El valor es obligatorio")
    return int(valor)


def _fecha(mensaje, defecto=None):
    valor = _texto(mensaje + " (AAAA-MM-DD o ISO 8601 con zona horaria)", defecto)
    if valor is None:
        raise ValueError("La fecha es obligatoria")
    if len(valor) == 10:
        return datetime.fromisoformat(valor).replace(tzinfo=timezone.utc)
    fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if fecha.tzinfo is None or fecha.utcoffset() is None:
        raise ValueError("La fecha debe incluir zona horaria")
    return fecha


def _falla(opciones):
    print("Escenarios de falla: " + ", ".join(opciones))
    valor = (_texto("Forzar falla (Enter = ninguna)") or "").upper()
    if not valor:
        return None
    if valor not in opciones:
        raise ValueError("Escenario de falla inválido")
    return valor


def _mostrar(resultado):
    print("\nResultado:")
    pprint(resultado, sort_dicts=False, width=110)


def _p1():
    from app.problemas.p1_cotizaciones import ejecutar_publicador

    print("Requiere cotizaciones iniciales cargadas en Redis.")
    instrumentos = _entero("Cantidad de instrumentos", "120")
    rondas = _entero("Rondas", "5")
    pausa = float(_texto("Pausa entre rondas (segundos)", "0.1"))
    _mostrar(ejecutar_publicador(instrumentos, rondas, pausa))


def _p2():
    from app.problemas.p2_colocar_orden import colocar_orden_compra

    from datetime import timedelta

    portafolio = _uuid("ID del portafolio")
    instrumento = _uuid("ID del instrumento")
    cantidad = _decimal("Cantidad")
    precio = _decimal("Precio límite")
    id_orden = _uuid("ID de orden (opcional)", opcional=True)
    minutos = _texto("Vence en N minutos (Enter = al cierre del mercado)")
    vencimiento = None
    if minutos:
        vencimiento = datetime.now(timezone.utc) + timedelta(minutes=int(minutos))
    falla = _falla(("ORDEN",))
    resultado = colocar_orden_compra(
        portafolio,
        instrumento,
        cantidad,
        precio,
        id_orden=id_orden,
        fecha_expiracion=vencimiento,
        forzar_falla=falla,
    )
    _mostrar(resultado)


def _p3():
    from app.problemas.p3_ejecucion import ejecutar_orden_compra

    id_orden = _uuid("ID de la orden")
    cantidad = _decimal("Cantidad a ejecutar")
    id_ejecucion = _uuid("ID de ejecución (opcional)", opcional=True)
    falla = _falla(("POSICION", "HISTORIAL", "SALDO"))
    _mostrar(ejecutar_orden_compra(id_orden, cantidad, id_ejecucion, falla))


def _p4():
    from app.problemas.p4_cancelacion import cancelar_orden, expirar_orden, expirar_ordenes

    print("1. Cancelar orden\n2. Expirar una orden\n3. Procesar órdenes vencidas\n0. Volver")
    opcion = _texto("Opción")
    if opcion == "1":
        id_orden = _uuid("ID de la orden")
        id_cancelacion = _uuid("ID de cancelación (opcional)", opcional=True)
        falla = _falla(("ORDEN", "SALDO"))
        _mostrar(cancelar_orden(id_orden, id_cancelacion, falla))
    elif opcion == "2":
        id_orden = _uuid("ID de la orden")
        id_cancelacion = _uuid("ID de cancelación (opcional)", opcional=True)
        falla = _falla(("ORDEN", "SALDO"))
        _mostrar(expirar_orden(id_orden, id_cancelacion=id_cancelacion, forzar_falla=falla))
    elif opcion == "3":
        _mostrar(expirar_ordenes())
    elif opcion != "0":
        print("Opción inválida")


def _p5():
    from app.problemas.p5_valor_portafolio import calcular_valor_portafolio

    _mostrar(calcular_valor_portafolio(_uuid("ID del portafolio")))


def _p6():
    from app.problemas.p6_historial import consultar_historial, calcular_rendimiento_12_meses

    print("1. Consultar historial\n2. Rendimiento de los últimos 12 meses\n0. Volver")
    opcion = _texto("Opción")
    if opcion == "1":
        id_usuario = _uuid("ID del usuario")
        desde = _fecha("Desde")
        hasta = _fecha("Hasta")
        instrumento = _uuid("ID del instrumento (opcional)", opcional=True)
        _mostrar(consultar_historial(id_usuario, desde, hasta, instrumento))
    elif opcion == "2":
        id_usuario = _uuid("ID del usuario")
        instrumento = _uuid("ID del instrumento (opcional)", opcional=True)
        _mostrar(calcular_rendimiento_12_meses(id_usuario, id_instrumento=instrumento))
    elif opcion != "0":
        print("Opción inválida")


def _p7():
    from app.problemas.p7_riesgo import detectar_concentracion_riesgo, detectar_operaciones_espejo

    print("1. Concentración sectorial\n2. Operaciones en espejo\n0. Volver")
    opcion = _texto("Opción")
    if opcion == "1":
        _mostrar(detectar_concentracion_riesgo(_decimal("Umbral porcentual", "50")))
    elif opcion == "2":
        desde = _fecha("Desde")
        hasta = _fecha("Hasta")
        ventana = _entero("Ventana en segundos", "5")
        minimo = _entero("Mínimo de usuarios", "2")
        _mostrar(detectar_operaciones_espejo(desde, hasta, ventana, minimo))
    elif opcion != "0":
        print("Opción inválida")


def _p8():
    from app.problemas.p8_suspension import suspender_instrumento, trazar_orden

    print("1. Suspender instrumento\n2. Trazar orden\n0. Volver")
    opcion = _texto("Opción")
    if opcion == "1":
        instrumento = _uuid("ID del instrumento")
        operador = _uuid("ID del operador")
        motivo = _texto("Motivo de suspensión")
        identificador = _uuid("ID de suspensión para reintento (opcional)", opcional=True) or uuid4()
        falla = _falla(("DESPUES_BLOQUEO", "DESPUES_CANCELACION", "AUDITORIA"))
        print(f"ID de suspensión (guardarlo para reintentar): {identificador}")
        _mostrar(suspender_instrumento(instrumento, operador, motivo, identificador, falla))
    elif opcion == "2":
        orden = _uuid("ID de la orden")
        margen = _entero("Margen de búsqueda en segundos", "1")
        _mostrar(trazar_orden(orden, margen))
    elif opcion != "0":
        print("Opción inválida")


def _verificar():
    from scripts.verificar_ambiente import main as verificar

    verificar()


def main():
    acciones = {
        "1": _p1, "2": _p2, "3": _p3, "4": _p4,
        "5": _p5, "6": _p6, "7": _p7, "8": _p8,
        "9": _verificar,
    }
    while True:
        print("\n" + "=" * 43)
        print("         TPO TRADING - MENÚ PRINCIPAL")
        print("=" * 43)
        print("1. Cotizaciones en tiempo real (P1)")
        print("2. Colocar orden de compra (P2)")
        print("3. Ejecutar orden total o parcial (P3)")
        print("4. Cancelar o expirar órdenes (P4)")
        print("5. Valuar portafolio (P5)")
        print("6. Historial y rendimiento (P6)")
        print("7. Riesgo y operaciones en espejo (P7)")
        print("8. Suspensión y trazabilidad (P8)")
        print("9. Verificar ambiente")
        print("0. Salir")
        opcion = _texto("Seleccione una opción")
        if opcion == "0":
            print("Hasta luego.")
            break
        accion = acciones.get(opcion)
        if accion is None:
            print("Opción inválida")
            continue
        try:
            accion()
        except (ValueError, RuntimeError, InvalidOperation) as error:
            print(f"\nError: {error}")
        except Exception as error:
            print(f"\nError inesperado ({type(error).__name__}): {error}")


if __name__ == "__main__":
    main()

