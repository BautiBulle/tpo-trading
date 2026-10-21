"""Carga inicial reproducible para la plataforma de trading.

Ejecutar desde la raíz (con las cuatro bases levantadas):
    python -m seed.cargar_datos

Deja el sistema listo para ejecutar los ocho problemas:

  MongoDB     1000 usuarios y portafolios, 120 instrumentos, 5 operadores,
              posiciones de los inversores con historial y órdenes pendientes.
  PostgreSQL  saldo inicial de cada portafolio y bloqueo de las órdenes pendientes.
  Redis       cotización vigente de los 120 instrumentos.
  Cassandra   50.000 cotizaciones históricas (entidad de mayor volumen),
              cierres diarios recientes e historial de operaciones de 12 meses.

Reproducible: los identificadores salen de uuid5 y los números aleatorios de
semillas fijas, así que dos cargas generan exactamente los mismos datos.
Las fechas del historial se calculan desde una "fecha de anclaje" que se guarda
en MongoDB la primera vez; las cargas siguientes reutilizan esa misma fecha.

Idempotente: se puede ejecutar varias veces sin duplicar nada (upsert en
MongoDB, ON CONFLICT / id de operación en PostgreSQL, misma clave primaria en
Cassandra).
"""

import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import NAMESPACE_DNS, uuid5

from bson.decimal128 import Decimal128

from app.config import get_mongo_db, get_pg

USUARIOS = 1000
INSTRUMENTOS = 120
COTIZACIONES_HISTORICAS = 50000
OPERADORES = 5

# Historial de operaciones (P5, P6, P7).
USUARIOS_CON_HISTORIAL = 300          # Usuario 1 a Usuario 300
USUARIOS_CONCENTRADOS = 30            # Usuario 1 a 30: todo en un mismo sector
GRUPOS_ESPEJO = 6                     # Usuario 301 a 318 (3 por grupo)
USUARIOS_POR_GRUPO_ESPEJO = 3

# Órdenes pendientes (P3, P4, P8).
ORDENES_SUSPENSION = 20               # Usuario 1 a 20 -> ACT002
ORDENES_VENCIDAS = 15                 # Usuario 21 a 35 -> ya vencidas
ORDENES_VIGENTES = 15                 # Usuario 36 a 50 -> vigentes
DIAS_CIERRES_RECIENTES = 10

SALDO_INICIAL = Decimal("100000.00")
CENTAVO = Decimal("0.01")

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


def simbolo_de(numero):
    return f"ACT{numero + 1:03d}"


def precio_base(numero):
    """Precio de referencia del instrumento (el mismo que se carga en Redis)."""
    return Decimal(100 + numero)


def redondear(valor):
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def fecha_anclaje():
    """Fecha fija de referencia del historial, guardada en MongoDB.

    La primera carga usa el inicio del día actual (UTC); las siguientes
    reutilizan la guardada para que los datos sean exactamente los mismos.
    """
    db = get_mongo_db()
    hoy = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    db.seed_info.update_one(
        {"_id": "carga_inicial"},
        {"$setOnInsert": {"fechaAnclaje": hoy}},
        upsert=True,
    )
    fecha = db.seed_info.find_one({"_id": "carga_inicial"})["fechaAnclaje"]
    return fecha.astimezone(timezone.utc)


# ---------------------------------------------------------------- MongoDB

def cargar_mongodb(anclaje):
    """Carga usuarios, portafolios, instrumentos y operadores."""
    db = get_mongo_db()

    print("Cargando MongoDB...")

    # Los usuarios existen desde antes del historial (P6 lee desde su alta).
    alta_usuarios = anclaje - timedelta(days=400)

    for numero in range(USUARIOS):
        usuario_id = identificador("usuario", numero)
        portafolio_id = identificador("portafolio", numero)

        db.usuarios.update_one(
            {"_id": str(usuario_id)},
            {
                "$set": {
                    "nombre": f"Usuario {numero + 1}",
                    "email": f"usuario{numero + 1}@trading.test",
                    "fechaCreacion": alta_usuarios,
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
                    "fechaCreacion": alta_usuarios,
                }
            },
            upsert=True,
        )

    for numero in range(INSTRUMENTOS):
        instrumento_id = identificador("instrumento", numero)

        db.instrumentos.update_one(
            {"_id": str(instrumento_id)},
            {
                "$setOnInsert": {
                    "simbolo": simbolo_de(numero),
                    "nombre": f"Empresa {numero + 1}",
                    "sector": SECTORES[numero % len(SECTORES)],
                    "estado": "ACTIVO",
                    "fechaCreacion": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )

    for numero in range(OPERADORES):
        db.operadores.update_one(
            {"_id": str(identificador("operador", numero))},
            {
                "$setOnInsert": {
                    "nombre": f"Operador {numero + 1}",
                    "matricula": f"MAT-{1000 + numero}",
                    "email": f"operador{numero + 1}@trading.test",
                    "estado": "ACTIVO",
                }
            },
            upsert=True,
        )

    print(
        f"MongoDB: {USUARIOS} usuarios, {USUARIOS} portafolios, "
        f"{INSTRUMENTOS} instrumentos y {OPERADORES} operadores."
    )


# ------------------------------------------------------------- PostgreSQL

def cargar_postgresql():
    """Deposita un saldo inicial por portafolio sin duplicarlo."""
    print("Cargando PostgreSQL...")

    conexion = get_pg()
    with conexion.transaction():
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
                        SALDO_INICIAL,
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
                        (SALDO_INICIAL, portafolio_id),
                    )

    print("PostgreSQL: saldos y depósitos iniciales cargados.")


# ------------------------------------------------------------------ Redis

def cargar_redis():
    """Carga precios iniciales utilizando el repositorio existente."""
    from app.repos.precios_redis import set_precio

    print("Cargando Redis...")

    fecha = datetime.now(timezone.utc)

    for numero in range(INSTRUMENTOS):
        base = precio_base(numero)
        set_precio(
            simbolo_de(numero),
            base - Decimal("0.50"),
            base + Decimal("0.50"),
            base,
            fecha,
        )

    print(f"Redis: {INSTRUMENTOS} cotizaciones actuales cargadas.")


# -------------------------------------------------------------- Cassandra

def _ejecutar_en_lotes(sesion, consulta, filas, aviso_cada=None):
    """Inserta filas en paralelo (mucho más rápido que de a una)."""
    from cassandra.concurrent import execute_concurrent_with_args

    lote = 2000
    for inicio in range(0, len(filas), lote):
        resultados = execute_concurrent_with_args(
            sesion, consulta, filas[inicio:inicio + lote], concurrency=64,
        )
        for correcto, resultado in resultados:
            if not correcto:
                raise resultado
        hechas = min(inicio + lote, len(filas))
        if aviso_cada and hechas % aviso_cada == 0:
            print(f"  {hechas} cotizaciones cargadas")


def cargar_cassandra():
    """Carga 50.000 cotizaciones históricas en Cassandra."""
    from app.config import get_cassandra
    from cassandra.util import Date

    print("Cargando Cassandra...")

    sesion = get_cassandra()

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
    filas = []

    for numero in range(COTIZACIONES_HISTORICAS):
        simbolo = f"ACT{numero % INSTRUMENTOS + 1:03d}"
        fecha = inicio + timedelta(minutes=numero)

        precio = Decimal(
            str(round(generador.uniform(50, 500), 2))
        )

        volumen = generador.randint(100, 10000)
        filas.append((
            simbolo,
            Date(fecha.date()),
            fecha,
            precio - Decimal("0.50"),
            precio + Decimal("0.50"),
            precio,
            volumen,
        ))

    _ejecutar_en_lotes(sesion, consulta, filas, aviso_cada=10000)

    print("Cassandra: 50.000 cotizaciones históricas cargadas.")


def cargar_cierres_recientes():
    """Cierre diario de los últimos días de cada instrumento (para el P5).

    El P5 calcula el rendimiento del día comparando el precio vigente con el
    último precio anterior al inicio del día. Las fechas se calculan desde
    hoy; cada cierre tiene una clave fija (instrumento, día, 20:00 UTC), así
    que repetir la carga el mismo día no duplica nada.
    """
    from app.config import get_cassandra
    from cassandra.util import Date

    sesion = get_cassandra()
    consulta = sesion.prepare(
        """
        INSERT INTO historico_cotizacion (
            id_instrumento, dia, fecha_hora,
            precio_compra, precio_venta, precio_ultimo, volumen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
    )

    hoy = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    filas = []
    for numero in range(INSTRUMENTOS):
        base = precio_base(numero)
        for dias_atras in range(1, DIAS_CIERRES_RECIENTES + 1):
            cierre = (hoy - timedelta(days=dias_atras)).replace(hour=20)
            # Semilla por instrumento y fecha: el mismo día da el mismo precio.
            generador = random.Random(f"{numero}-{cierre.date()}")
            precio = redondear(base * Decimal(str(generador.uniform(0.96, 1.04))))
            filas.append((
                simbolo_de(numero),
                Date(cierre.date()),
                cierre,
                precio - Decimal("0.50"),
                precio + Decimal("0.50"),
                precio,
                generador.randint(1000, 50000),
            ))

    _ejecutar_en_lotes(sesion, consulta, filas)
    print(
        f"Cassandra: cierres de los últimos {DIAS_CIERRES_RECIENTES} días "
        f"de los {INSTRUMENTOS} instrumentos."
    )


# ------------------------------------------- Historial de operaciones

def _generar_operaciones(anclaje):
    """Devuelve la lista de operaciones históricas (compras y ventas).

    - Usuario 1 a 30 invierten solo en instrumentos de un mismo sector
      (los detecta la concentración de riesgo del P7).
    - Usuario 31 a 300 diversifican entre sectores.
    - Usuario 301 a 318 forman grupos que operan "en espejo": mismo
      instrumento, mismo sentido, con pocos segundos de diferencia (P7).
    Cada usuario solo vende lo que compró antes, así el rendimiento del P6
    se puede calcular.
    """
    generador = random.Random(2026)
    operaciones = []
    inicio = anclaje - timedelta(days=360)

    for usuario in range(USUARIOS_CON_HISTORIAL):
        if usuario < USUARIOS_CONCENTRADOS:
            sector = usuario % len(SECTORES)
            candidatos = [n for n in range(INSTRUMENTOS) if n % len(SECTORES) == sector]
            instrumentos = generador.sample(candidatos, generador.randint(3, 6))
        else:
            # Un instrumento de cada sector distinto: cartera diversificada.
            sectores = generador.sample(range(len(SECTORES)), generador.randint(4, 6))
            instrumentos = [
                generador.randrange(sector, INSTRUMENTOS, len(SECTORES))
                for sector in sectores
            ]

        for orden_instrumento, numero in enumerate(instrumentos):
            base = precio_base(numero)
            # Fechas ordenadas y separadas: nunca hay compra y venta simultáneas.
            cantidad_movimientos = generador.randint(2, 5)
            fechas = sorted(
                inicio + timedelta(seconds=generador.randint(0, 358 * 86400))
                for _ in range(cantidad_movimientos)
            )
            tenencia = 0
            for indice, fecha in enumerate(fechas):
                vender = indice > 0 and tenencia > 0 and generador.random() < 0.4
                if vender:
                    cantidad = generador.randint(1, tenencia)
                    factor = generador.uniform(0.92, 1.20)
                    tipo = "VENTA"
                    tenencia -= cantidad
                else:
                    cantidad = generador.randint(1, 20)
                    factor = generador.uniform(0.85, 1.05)
                    tipo = "COMPRA"
                    tenencia += cantidad
                operaciones.append({
                    "id": identificador(
                        "operacion", f"{usuario}-{orden_instrumento}-{indice}"
                    ),
                    "usuario": usuario,
                    "instrumento": numero,
                    "fecha": fecha.replace(microsecond=0),
                    "tipo": tipo,
                    "cantidad": Decimal(cantidad),
                    "precio": redondear(base * Decimal(str(factor))),
                })

    # Grupos espejo: días recientes, 3 usuarios con 2 segundos de diferencia.
    for grupo in range(GRUPOS_ESPEJO):
        numero = 10 + grupo * 7
        base = precio_base(numero)
        compra = (anclaje - timedelta(days=grupo + 2)).replace(hour=15)
        for posicion in range(USUARIOS_POR_GRUPO_ESPEJO):
            usuario = USUARIOS_CON_HISTORIAL + grupo * USUARIOS_POR_GRUPO_ESPEJO + posicion
            desfase = timedelta(seconds=posicion * 2)
            operaciones.append({
                "id": identificador("operacion-espejo", f"{grupo}-{posicion}-compra"),
                "usuario": usuario, "instrumento": numero,
                "fecha": compra + desfase, "tipo": "COMPRA",
                "cantidad": Decimal(50), "precio": base,
            })
            # La mitad de los grupos también vende en espejo al día siguiente.
            if grupo % 2 == 1:
                operaciones.append({
                    "id": identificador("operacion-espejo", f"{grupo}-{posicion}-venta"),
                    "usuario": usuario, "instrumento": numero,
                    "fecha": compra + timedelta(days=1) + desfase, "tipo": "VENTA",
                    "cantidad": Decimal(30), "precio": redondear(base * Decimal("1.05")),
                })

    return operaciones


def cargar_historial_operaciones(anclaje):
    """Escribe el historial en Cassandra y las posiciones que resultan en MongoDB."""
    from app.config import get_cassandra

    print("Cargando historial de operaciones...")
    operaciones = _generar_operaciones(anclaje)

    sesion = get_cassandra()
    por_usuario = sesion.prepare(
        """
        INSERT INTO operaciones_por_usuario (
            id_usuario, mes, fecha_hora, id_operacion,
            id_instrumento, tipo, cantidad, precio, importe
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    )
    por_instrumento = sesion.prepare(
        """
        INSERT INTO operaciones_por_instrumento (
            id_instrumento, dia, fecha_hora, id_operacion,
            id_usuario, tipo, cantidad, precio
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
    )

    filas_usuario = []
    filas_instrumento = []
    for op in operaciones:
        usuario_id = identificador("usuario", op["usuario"])
        simbolo = simbolo_de(op["instrumento"])
        filas_usuario.append((
            usuario_id, op["fecha"].strftime("%Y-%m"), op["fecha"], op["id"],
            simbolo, op["tipo"], op["cantidad"], op["precio"],
            op["cantidad"] * op["precio"],
        ))
        filas_instrumento.append((
            simbolo, op["fecha"].date(), op["fecha"], op["id"],
            usuario_id, op["tipo"], op["cantidad"], op["precio"],
        ))

    _ejecutar_en_lotes(sesion, por_usuario, filas_usuario)
    _ejecutar_en_lotes(sesion, por_instrumento, filas_instrumento)

    # Posición resultante: cantidad neta y precio promedio ponderado de compra.
    posiciones = defaultdict(lambda: {"cantidad": Decimal(0), "costo": Decimal(0)})
    for op in sorted(operaciones, key=lambda o: o["fecha"]):
        posicion = posiciones[(op["usuario"], op["instrumento"])]
        if op["tipo"] == "COMPRA":
            posicion["cantidad"] += op["cantidad"]
            posicion["costo"] += op["cantidad"] * op["precio"]
        else:
            promedio = posicion["costo"] / posicion["cantidad"]
            posicion["cantidad"] -= op["cantidad"]
            posicion["costo"] = promedio * posicion["cantidad"]

    db = get_mongo_db()
    cargadas = 0
    for (usuario, numero), posicion in posiciones.items():
        if posicion["cantidad"] <= 0:
            continue
        promedio = redondear(posicion["costo"] / posicion["cantidad"])
        # $setOnInsert: si después se operó con el P3, no se pisa la posición.
        db.posiciones.update_one(
            {
                "idPortafolio": str(identificador("portafolio", usuario)),
                "idInstrumento": str(identificador("instrumento", numero)),
            },
            {
                "$setOnInsert": {
                    "cantidad": Decimal128(posicion["cantidad"]),
                    "precioPromedio": Decimal128(promedio),
                    "fechaActualizacion": anclaje,
                }
            },
            upsert=True,
        )
        cargadas += 1

    ventas = sum(1 for op in operaciones if op["tipo"] == "VENTA")
    print(
        f"Cassandra: {len(operaciones)} operaciones históricas "
        f"({len(operaciones) - ventas} compras, {ventas} ventas)."
    )
    print(f"MongoDB: {cargadas} posiciones abiertas.")


# --------------------------------------------------- Órdenes pendientes

def _ordenes_a_crear(anclaje):
    from app.constantes import cierre_de_mercado

    vigente = cierre_de_mercado(anclaje + timedelta(days=30))
    vencida = cierre_de_mercado(anclaje - timedelta(days=2))
    ordenes = []
    usuario = 0
    for _ in range(ORDENES_SUSPENSION):
        ordenes.append((usuario, 1, vigente))          # ACT002
        usuario += 1
    for indice in range(ORDENES_VENCIDAS):
        ordenes.append((usuario, 20 + indice, vencida))
        usuario += 1
    for indice in range(ORDENES_VIGENTES):
        ordenes.append((usuario, 40 + indice, vigente))
        usuario += 1
    return ordenes


def cargar_ordenes_pendientes(anclaje):
    """Órdenes de compra pendientes con su saldo bloqueado.

    - 20 sobre ACT002 (para demostrar la suspensión del P8).
    - 15 ya vencidas (para "Procesar órdenes vencidas" del P4).
    - 15 vigentes (para ejecutar con el P3 o cancelar con el P4).
    El precio límite es el precio de venta vigente, así el P3 puede ejecutarlas.
    Mismo orden que el P2: primero se bloquea el saldo y después se crea la orden.
    """
    from app.repos.mongo_repo import crear_orden, obtener_instrumento, obtener_orden
    from app.repos.saldo_pg import bloquear, liberar

    print("Cargando órdenes pendientes...")
    creadas = existentes = omitidas = 0
    cantidad = Decimal(5)

    for usuario, numero, vencimiento in _ordenes_a_crear(anclaje):
        id_orden = identificador("orden", usuario)
        id_portafolio = identificador("portafolio", usuario)
        if obtener_orden(id_orden) is not None:
            existentes += 1
            continue

        id_instrumento = identificador("instrumento", numero)
        if obtener_instrumento(id_instrumento)["estado"] != "ACTIVO":
            # Por ejemplo, si el instrumento quedó suspendido en una demo del P8.
            print(f"  Orden de Usuario {usuario + 1} omitida: {simbolo_de(numero)} no está activo")
            omitidas += 1
            continue

        limite = precio_base(numero) + Decimal("0.50")
        importe = (cantidad * limite).quantize(CENTAVO)
        bloquear(id_portafolio, importe, identificador("bloqueo-orden", usuario), id_orden)
        try:
            crear_orden(
                id_orden, id_portafolio, id_instrumento,
                "COMPRA", cantidad, limite, vencimiento,
            )
        except Exception:
            # Igual que el P2: si no se pudo registrar la orden, se libera el saldo.
            liberar(id_portafolio, importe, identificador("liberacion-orden", usuario), id_orden)
            raise
        creadas += 1

    print(
        f"Órdenes pendientes: {creadas} creadas, {existentes} ya existían"
        + (f", {omitidas} omitidas." if omitidas else ".")
    )


# ------------------------------------------------------------------ Main

def imprimir_datos_de_prueba(anclaje):
    def linea(nombre, valor):
        print(f"  {nombre:<38} {valor}")

    espejo_desde = (anclaje - timedelta(days=GRUPOS_ESPEJO + 2)).date()
    espejo_hasta = anclaje.date()
    print("\nDatos para probar desde el menú (python -m app.main):")
    linea("Usuario 1 (con historial)", identificador("usuario", 0))
    linea("Portafolio del Usuario 1", identificador("portafolio", 0))
    linea("Instrumento ACT001", identificador("instrumento", 0))
    linea("Instrumento ACT002 (P8: 20 órdenes)", identificador("instrumento", 1))
    linea("Orden vigente del Usuario 1 (ACT002)", identificador("orden", 0))
    linea("Orden vencida del Usuario 21", identificador("orden", ORDENES_SUSPENSION))
    linea("Orden vigente del Usuario 36", identificador("orden", ORDENES_SUSPENSION + ORDENES_VENCIDAS))
    linea("Operador 1", identificador("operador", 0))
    linea("P7 espejo: rango de fechas", f"{espejo_desde} a {espejo_hasta}")


def main():
    from init.mongo_indexes import main as crear_indices

    crear_indices()
    anclaje = fecha_anclaje()
    print(f"Fecha de anclaje del historial: {anclaje.date()}")

    cargar_mongodb(anclaje)
    cargar_postgresql()
    cargar_redis()
    cargar_cassandra()
    cargar_cierres_recientes()
    cargar_historial_operaciones(anclaje)
    cargar_ordenes_pendientes(anclaje)

    print("Carga inicial finalizada.")
    print("Total: más de 58.000 registros.")
    imprimir_datos_de_prueba(anclaje)


if __name__ == "__main__":
    main()
