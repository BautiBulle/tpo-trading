-- Cassandra: keyspace + tablas de historial (esquema inicial del plan, sección 9)
-- Lo ejecuta el contenedor cassandra-init al hacer docker compose up.
-- Las particiones llevan un bucket de tiempo (día / mes) para que no crezcan sin límite.

CREATE KEYSPACE IF NOT EXISTS tpo_trading
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE tpo_trading;

CREATE TABLE IF NOT EXISTS historico_cotizacion (
    id_instrumento text,
    dia            date,
    fecha_hora     timestamp,
    precio_compra  decimal,
    precio_venta   decimal,
    precio_ultimo  decimal,
    volumen        bigint,
    PRIMARY KEY ((id_instrumento, dia), fecha_hora)
) WITH CLUSTERING ORDER BY (fecha_hora DESC);

CREATE TABLE IF NOT EXISTS operaciones_por_usuario (
    id_usuario     uuid,
    mes            text,
    fecha_hora     timestamp,
    id_operacion   uuid,
    id_instrumento text,
    tipo           text,
    cantidad       decimal,
    precio         decimal,
    importe        decimal,
    PRIMARY KEY ((id_usuario, mes), fecha_hora, id_operacion)
) WITH CLUSTERING ORDER BY (fecha_hora DESC, id_operacion ASC);

-- La usa el problema 7
CREATE TABLE IF NOT EXISTS operaciones_por_instrumento (
    id_instrumento text,
    dia            date,
    fecha_hora     timestamp,
    id_operacion   uuid,
    id_usuario     uuid,
    tipo           text,
    cantidad       decimal,
    precio         decimal,
    PRIMARY KEY ((id_instrumento, dia), fecha_hora, id_operacion)
);

CREATE TABLE IF NOT EXISTS auditoria_por_instrumento (
    id_instrumento text,
    fecha_hora     timestamp,
    id_registro    uuid,
    accion         text,
    motivo         text,
    id_operador    uuid,
    PRIMARY KEY ((id_instrumento), fecha_hora, id_registro)
);
