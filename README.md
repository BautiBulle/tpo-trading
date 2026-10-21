# TPO Trading — Persistencia políglota

Plataforma de trading con **PostgreSQL** (saldos), **MongoDB** (usuarios, instrumentos, portafolios, órdenes, sagas), **Redis** (precio vigente) y **Cassandra** (historial y auditoría).

## Requisitos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (o Docker Engine + Compose v2)
- Python 3.11 o superior
- ~3 GB de RAM libres para los contenedores (Cassandra es la que más usa)

## Levantar el ambiente desde cero

Todos los comandos se corren desde la raíz del proyecto.

```bash
# 1. Bases de datos (la primera vez descarga las imágenes; Cassandra tarda ~1-2 min en quedar lista)
docker compose up -d

# 2. Esperar a que todo esté "healthy" y que cassandra-init termine con "Exited (0)"
docker compose ps -a
docker compose logs cassandra-init      # debe decir "Cassandra inicializada OK"

# 3. Entorno de Python
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements.txt

# 4. Colecciones e índices de MongoDB
python -m init.mongo_indexes

# 5. Verificar que las 4 bases respondan
python -m scripts.verificar_ambiente
```

Si todo está bien, el paso 5 termina con `Ambiente listo: las 4 bases responden.`

### Qué inicializa cada cosa

| Base | Cómo se inicializa | Cuándo |
|---|---|---|
| PostgreSQL | `init/postgres.sql` (montado en el contenedor) | Automático, la primera vez que se crea el volumen |
| MongoDB | Replica set `rs0` (lo inicia el healthcheck) + `init/mongo_indexes.py` | Replica set automático; índices a mano (paso 4) |
| Redis | `--appendonly yes` (AOF) | Automático |
| Cassandra | Contenedor `cassandra-init` corre `init/cassandra.cql` | Automático, espera a Cassandra con reintentos cada 5 s |

## Cargar los datos y ejecutar los problemas

```bash
python -m seed.cargar_datos      # deja el sistema listo para los 8 problemas
python -m app.main               # menú: una opción por problema
```

La carga es reproducible (mismos IDs y mismos datos en cualquier máquina) y se puede repetir sin duplicar nada. Al final imprime los IDs para probar. Los principales:

| Qué | ID |
|---|---|
| Usuario 1 (tiene historial y posiciones) | `f43ca51c-8ce6-5786-ac8e-c6ce57bd18b8` |
| Portafolio del Usuario 1 | `d72c0794-0ddd-5a08-86b3-0cc8e8ca4a0e` |
| Instrumento ACT001 | `dd88fda6-b002-5390-8bf3-11c2d8acc295` |
| Instrumento ACT002 (tiene 20 órdenes pendientes) | `cdd13043-e44c-54c3-b974-c105c571d278` |
| Orden vigente del Usuario 1 (ACT002) | `354cc0b0-4eaf-52ee-a075-1dd563fc67cc` |
| Orden ya vencida del Usuario 21 | `2d8ba71c-b76d-5515-85d0-b28677f00a76` |
| Orden vigente del Usuario 36 | `ea12e1ea-d280-57f9-b17c-dd99f9ec677c` |
| Operador 1 | `3567096d-e1fe-5e0b-ab6b-c15e489d0b25` |

Qué hay cargado para cada problema:

| Problema | Datos de la carga inicial |
|---|---|
| P1 | Precio vigente de los 120 instrumentos en Redis |
| P2 | 1000 portafolios con $100.000 de saldo |
| P3 | 35 órdenes vigentes (límite = precio vigente, se pueden ejecutar) |
| P4 | 15 órdenes ya vencidas (opción "Procesar órdenes vencidas") y 35 vigentes para cancelar |
| P5 | Posiciones de los usuarios 1 a 318 y cierres de los últimos 10 días |
| P6 | Historial de 12 meses (≈5.000 compras y ventas) de los usuarios 1 a 318 |
| P7 | Usuarios 1 a 30 concentrados en un sector; 6 grupos que operan en espejo (usuarios 301 a 318) en la última semana |
| P8 | ACT002 con 20 órdenes pendientes para suspender |

### Escenarios de falla

Cada problema con rollback pide, desde el menú, qué falla forzar (Enter = ninguna):

| Problema | Falla | Qué demuestra |
|---|---|---|
| P2 | `ORDEN` | Falla el registro de la orden en MongoDB: se libera el saldo bloqueado en PostgreSQL |
| P3 | `POSICION`, `HISTORIAL`, `SALDO` | Falla un paso de la ejecución: se deshacen en orden inverso los pasos ya hechos |
| P4 | `ORDEN`, `SALDO` | Falla la cancelación: la orden vuelve a su estado y el saldo queda bloqueado como estaba |
| P8 | `DESPUES_BLOQUEO`, `DESPUES_CANCELACION`, `AUDITORIA` | Falla la suspensión a mitad de camino: ninguna orden cancelada queda con saldo bloqueado; se reintenta con el mismo ID de suspensión |

El estado de cada operación queda en la colección `sagas` de MongoDB (pasos completados y estado final: `COMPLETADA`, `COMPENSADA` o `REQUIERE_REVISION`).

## Comandos útiles

```bash
docker compose ps -a                 # estado de los contenedores
docker compose logs -f cassandra     # ver logs de una base
docker compose stop                  # apagar sin perder datos
docker compose down -v               # borrar TODO (contenedores + datos) para empezar de cero

# Consolas de cada base
docker exec -it tpo-postgres psql -U tpo -d trading
docker exec -it tpo-mongo mongosh trading
docker exec -it tpo-redis redis-cli
docker exec -it tpo-cassandra cqlsh -k tpo_trading
```

## Conexión

| Base | Host:puerto | Credenciales / base |
|---|---|---|
| PostgreSQL | `localhost:5432` | usuario `tpo`, clave `tpo`, base `trading` |
| MongoDB | `localhost:27017` | sin auth, base `trading`, replica set `rs0` |
| Redis | `localhost:6379` | sin auth |
| Cassandra | `localhost:9042` | sin auth, keyspace `tpo_trading` |

Si un puerto ya está ocupado en tu máquina (por ejemplo, tenés un Postgres instalado), copiá `.env.example` a `.env` y cambiá el puerto: lo leen tanto Docker Compose como Python.

## Estructura

```
tpo-trading/
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── init/
│   ├── postgres.sql          tablas saldo y movimiento_saldo
│   ├── cassandra.cql         keyspace + tablas de historial
│   └── mongo_indexes.py      colecciones e índices
├── app/
│   ├── main.py               menú de consola
│   ├── config.py             conexiones a las 4 bases
│   ├── constantes.py         estados de la orden y cierre del mercado
│   ├── repos/                solo acceso a datos, uno por base
│   │   ├── saldo_pg.py
│   │   ├── mongo_repo.py
│   │   ├── posiciones_mongo.py
│   │   ├── precios_redis.py
│   │   └── historial_cass.py
│   └── problemas/            un archivo por problema (p1 ... p8); cada uno
│                             maneja su saga y su parámetro forzar_falla
├── seed/cargar_datos.py      carga inicial reproducible
├── docs/                     documentación técnica por base
├── scripts/verificar_ambiente.py
└── tests/
```

**Regla clave:** los problemas nunca hablan directo con una base; siempre pasan por `app/repos/`, y los repos obtienen las conexiones de `app/config.py`.

## Convenciones

- IDs: UUID generados en Python (`idUsuario`, `idPortafolio`, `idOrden`, `idOperacion`). El mismo `idPortafolio` en MongoDB y PostgreSQL.
- Dinero con `Decimal`, nunca `float`.
- Fechas en UTC.
- Estados de la orden en `app/constantes.py`.
- Rama `main` protegida: cada uno trabaja en su rama y se mergea por Pull Request.

## Problemas comunes

- **Cassandra se reinicia o queda "unhealthy"**: suele ser falta de memoria. Darle más RAM a Docker Desktop (Settings → Resources) o cerrar otras cosas.
- **`cassandra-init` terminó con error**: correrlo de nuevo con `docker compose up cassandra-init`.
- **Mongo: "No replica set members match selector"**: esperar unos segundos a que el healthcheck inicie el replica set (`docker compose ps` tiene que mostrarlo healthy).
- **Cambié `init/postgres.sql` y no se aplica**: solo corre con el volumen vacío. Hacer `docker compose down -v` y volver a levantar.
