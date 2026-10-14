"""Verifica que las 4 bases estén levantadas e inicializadas.

Uso (desde la raíz del proyecto):
    python -m scripts.verificar_ambiente

No modifica datos: solo lee (en Redis escribe y borra una clave de prueba).
"""
import sys

from app import config

OK, FALLA = "OK   ", "FALLA"


def check_postgres():
    conn = config.get_pg()
    with conn.cursor() as cur:
        cur.execute("SELECT version()")
        version = cur.fetchone()[0].split(",")[0]
        cur.execute("""SELECT table_name FROM information_schema.tables
                       WHERE table_schema = 'public' ORDER BY table_name""")
        tablas = [r[0] for r in cur.fetchall()]
    conn.rollback()
    faltan = {"saldo", "movimiento_saldo"} - set(tablas)
    if faltan:
        raise RuntimeError(f"faltan tablas {sorted(faltan)} (¿se corrió init/postgres.sql?)")
    return f"{version} · tablas: {', '.join(tablas)}"


def check_mongo():
    db = config.get_mongo_db()
    info = db.client.admin.command("hello")
    if info.get("setName") != "rs0":
        raise RuntimeError("Mongo no está como replica set rs0")
    colecciones = sorted(db.list_collection_names())
    if "ordenes" not in colecciones:
        raise RuntimeError("no hay colecciones (correr: python -m init.mongo_indexes)")
    version = db.client.server_info()["version"]
    return f"MongoDB {version} · replica set {info['setName']} · colecciones: {', '.join(colecciones)}"


def check_redis():
    r = config.get_redis()
    r.ping()
    r.set("tpo:check", "ok", ex=10)
    assert r.get("tpo:check") == "ok"
    r.delete("tpo:check")
    info = r.info()
    aof = "AOF activado" if info.get("aof_enabled") else "AOF DESACTIVADO"
    return f"Redis {info['redis_version']} · {aof}"


def check_cassandra():
    s = config.get_cassandra()
    version = s.execute("SELECT release_version FROM system.local").one()[0]
    tablas = sorted(r.table_name for r in s.execute(
        "SELECT table_name FROM system_schema.tables WHERE keyspace_name = %s",
        [config.CASSANDRA_KEYSPACE]))
    return f"Cassandra {version} · keyspace {config.CASSANDRA_KEYSPACE} · tablas: {', '.join(tablas)}"


def main():
    checks = [("PostgreSQL", check_postgres), ("MongoDB", check_mongo),
              ("Redis", check_redis), ("Cassandra", check_cassandra)]
    fallas = 0
    for nombre, fn in checks:
        try:
            print(f"[{OK}] {nombre:<10} {fn()}")
        except Exception as e:  # noqa: BLE001 - queremos ver cualquier error
            fallas += 1
            print(f"[{FALLA}] {nombre:<10} {type(e).__name__}: {e}")
    config.cerrar_todo()
    print()
    if fallas:
        print(f"{fallas} base(s) con problemas. Revisar 'docker compose ps' y el README.")
        sys.exit(1)
    print("Ambiente listo: las 4 bases responden.")


if __name__ == "__main__":
    main()
