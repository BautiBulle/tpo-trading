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
│   ├── config.py             conexiones + parámetro FALLAR_EN
│   ├── constantes.py         estados de la orden
│   ├── repos/                UNA clase por base, solo acceso a datos
│   │   ├── saldo_pg.py
│   │   ├── mongo_repo.py
│   │   ├── precios_redis.py
│   │   └── historial_cass.py
│   ├── saga.py               orquestador de sagas
│   ├── problemas/            un archivo por problema (p1 ... p8)
│   └── fallas.py             inyección de fallas para la defensa
├── seed/cargar_datos.py
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
