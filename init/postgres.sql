-- PostgreSQL: saldos y movimientos de saldo (esquema inicial del plan, sección 9)
-- Se ejecuta automáticamente la primera vez que se levanta el contenedor.
-- Para volver a correrlo: docker compose down -v && docker compose up -d

SET TIME ZONE 'UTC';

CREATE TABLE IF NOT EXISTS saldo (
    id_portafolio    UUID PRIMARY KEY,
    saldo_disponible NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (saldo_disponible >= 0),
    saldo_bloqueado  NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (saldo_bloqueado >= 0)
);

CREATE TABLE IF NOT EXISTS movimiento_saldo (
    id_movimiento UUID PRIMARY KEY,
    id_portafolio UUID NOT NULL REFERENCES saldo,
    tipo          TEXT NOT NULL CHECK (tipo IN
                    ('DEPOSITO','RETIRO','BLOQUEO','LIBERACION','CONSUMO','REVERSION_CONSUMO')),
    importe       NUMERIC(18,2) NOT NULL CHECK (importe > 0),
    id_orden      UUID,
    id_operacion  UUID NOT NULL,                       -- idempotencia de la saga
    fecha_hora    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (id_operacion, tipo)                        -- repetir un paso no duplica
);

CREATE INDEX IF NOT EXISTS idx_mov_portafolio ON movimiento_saldo (id_portafolio, fecha_hora);
CREATE INDEX IF NOT EXISTS idx_mov_orden      ON movimiento_saldo (id_orden);
