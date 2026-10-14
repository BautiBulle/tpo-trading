"""MongoDB: crea las colecciones y los índices mínimos (plan, sección 9).

Uso (desde la raíz del proyecto, con las bases levantadas):
    python -m init.mongo_indexes

Se puede correr las veces que haga falta: si ya existen, no hace nada.
"""
from pymongo import ASCENDING

from app.config import get_mongo_db

COLECCIONES = ["usuarios", "operadores", "instrumentos", "portafolios", "ordenes", "sagas"]

INDICES = {
    "ordenes": [
        ([("estado", ASCENDING), ("fechaExpiracion", ASCENDING)], {}),
        ([("idPortafolio", ASCENDING), ("fechaCreacion", ASCENDING)], {}),
        ([("idInstrumento", ASCENDING), ("estado", ASCENDING)], {}),
    ],
    "instrumentos": [
        ([("simbolo", ASCENDING)], {"unique": True}),
    ],
    "sagas": [
        ([("estado", ASCENDING)], {}),
    ],
}


def main():
    db = get_mongo_db()
    existentes = set(db.list_collection_names())
    for nombre in COLECCIONES:
        if nombre not in existentes:
            db.create_collection(nombre)
            print(f"  colección creada: {nombre}")
    for coleccion, indices in INDICES.items():
        for claves, opciones in indices:
            nombre = db[coleccion].create_index(claves, **opciones)
            print(f"  índice OK: {coleccion}.{nombre}")
    print("MongoDB inicializado OK")


if __name__ == "__main__":
    main()
