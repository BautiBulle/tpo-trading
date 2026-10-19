"""Configuración y conexiones a las 4 bases.

Los valores se leen de variables de entorno (o del archivo .env). Si no hay .env,
se usan los mismos valores por defecto que el docker-compose.yml.

Cada función get_* devuelve una conexión/cliente reutilizable (se crea una sola vez).
Los repos (app/repos/) son los únicos que deberían llamar a estas funciones.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv es opcional
    pass

# ---------- Parámetros ----------
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "tpo")
PG_PASSWORD = os.getenv("PG_PASSWORD", "tpo")
PG_DB = os.getenv("PG_DB", "trading")

MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DB = os.getenv("MONGO_DB", "trading")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

CASSANDRA_HOST = os.getenv("CASSANDRA_HOST", "localhost")
CASSANDRA_PORT = int(os.getenv("CASSANDRA_PORT", "9042"))
CASSANDRA_KEYSPACE = os.getenv("CASSANDRA_KEYSPACE", "tpo_trading")

# Inyección de fallas para la defensa: nombre del paso donde fallar (vacío = no fallar)
FALLAR_EN = os.getenv("FALLAR_EN", "").strip() or None


# ---------- Conexiones ----------
_pg = _mongo = _redis = _cass = None


def get_pg():
    """Conexión psycopg 3 a PostgreSQL (autocommit apagado: manejar transacciones a mano)."""
    global _pg
    if _pg is None or _pg.closed:
        import psycopg
        _pg = psycopg.connect(
            host=PG_HOST, port=PG_PORT, user=PG_USER,
            password=PG_PASSWORD, dbname=PG_DB, connect_timeout=5,
            autocommit=True,
        )
        with _pg.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")
    return _pg


def get_mongo_db():
    """Base de MongoDB (pymongo). directConnection porque es un replica set de 1 nodo."""
    global _mongo
    if _mongo is None:
        from pymongo import MongoClient
        _mongo = MongoClient(
            f"mongodb://{MONGO_HOST}:{MONGO_PORT}/?replicaSet=rs0&directConnection=true",
            serverSelectionTimeoutMS=5000, tz_aware=True,
        )
    return _mongo[MONGO_DB]


def get_redis():
    """Cliente Redis con respuestas como str (no bytes)."""
    global _redis
    if _redis is None:
        import redis
        _redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
                             socket_connect_timeout=5)
    return _redis


def get_cassandra():
    """Sesión de Cassandra ya posicionada en el keyspace del TP."""
    global _cass
    if _cass is None:
        from cassandra.cluster import Cluster
        cluster = Cluster([CASSANDRA_HOST], port=CASSANDRA_PORT, connect_timeout=10)
        _cass = cluster.connect(CASSANDRA_KEYSPACE)
    return _cass


def cerrar_todo():
    """Cierra las conexiones abiertas (llamar al salir del programa)."""
    global _pg, _mongo, _redis, _cass
    if _pg is not None:
        _pg.close()
    if _mongo is not None:
        _mongo.close()
    if _redis is not None:
        _redis.close()
    if _cass is not None:
        _cass.cluster.shutdown()
    _pg = _mongo = _redis = _cass = None
