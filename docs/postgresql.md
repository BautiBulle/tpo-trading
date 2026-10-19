# PostgreSQL - Gestión de saldos y movimientos

## 1. Objetivo

PostgreSQL se utiliza para administrar los saldos financieros
de los portafolios de la plataforma de trading.

Es responsable de garantizar la consistencia de los movimientos
monetarios mediante transacciones ACID.

Dentro de la arquitectura de persistencia políglota:

- PostgreSQL administra saldos y reservas de fondos.
- MongoDB administra usuarios, órdenes y portafolios.
- Redis almacena las cotizaciones vigentes.
- Cassandra almacena información histórica y auditoría.

## 2. Modelo de datos

El esquema se define en el script SQL de inicialización
de PostgreSQL, ubicado en la carpeta `init`.

### Tabla saldo

Contiene:

- id_portafolio: identificador UUID y clave primaria.
- saldo_disponible: dinero disponible para operar.
- saldo_bloqueado: dinero reservado para órdenes.

Los importes utilizan NUMERIC(18,2).

Ambos saldos tienen restricciones CHECK para impedir
valores negativos.

### Tabla movimiento_saldo

Registra los movimientos financieros realizados.

Campos principales:

- id_movimiento: identificador UUID del movimiento.
- id_portafolio: referencia al portafolio.
- tipo: clase de movimiento financiero.
- importe: monto del movimiento.
- id_orden: identificador opcional de la orden.
- id_operacion: identificador utilizado para idempotencia.
- fecha_hora: fecha y hora del movimiento.

Los tipos permitidos son:

- DEPOSITO
- RETIRO
- BLOQUEO
- LIBERACION
- CONSUMO

La restricción UNIQUE (id_operacion, tipo) evita registrar
dos veces el mismo paso de una operación.

## 3. Repositorio implementado

Archivo:

    app/repos/saldo_pg.py

Funciones disponibles:

### depositar()

Incrementa el saldo disponible del portafolio.

### retirar()

Descuenta dinero del saldo disponible.

Rechaza la operación cuando no existen fondos suficientes.

### bloquear()

Reserva fondos para una orden de compra.

Descuenta el importe del saldo disponible y lo suma
al saldo bloqueado.

### liberar()

Devuelve fondos previamente bloqueados al saldo disponible.

### consumir()

Descuenta definitivamente fondos del saldo bloqueado
cuando corresponde ejecutar una compra.

### consultar_saldo()

Devuelve el saldo disponible y bloqueado de un portafolio.

Si el portafolio no tiene un registro de saldo, devuelve None.

## 4. Transacciones ACID

Cada movimiento se ejecuta dentro de una transacción
PostgreSQL utilizando psycopg 3.

La implementación utiliza:

    with conexion.transaction():

Si todos los pasos terminan correctamente, la transacción
se confirma.

Si ocurre un error, los cambios de esa transacción
se revierten.

De esta manera, la actualización de los saldos y el
registro del movimiento forman parte de una misma
operación transaccional.

## 5. Control de concurrencia

Antes de modificar los saldos, el repositorio ejecuta
una consulta con:

    SELECT ... FOR UPDATE

Esto bloquea la fila del portafolio durante la transacción.

El objetivo es evitar que dos operaciones simultáneas
modifiquen incorrectamente los mismos fondos.

La implementación también utiliza las restricciones
CHECK del esquema para impedir saldos negativos.

## 6. Idempotencia

Cada movimiento recibe un identificador id_operacion.

Antes de registrar un movimiento, el repositorio comprueba
si ya existe uno con el mismo id_operacion y tipo.

Si encuentra un movimiento idéntico, devuelve False
sin volver a modificar los saldos.

Si encuentra un movimiento con el mismo identificador
pero con datos diferentes, genera un error.

Esto permite reintentar pasos de una saga sin duplicar
sus efectos financieros en los escenarios implementados.

## 7. Validaciones

El repositorio verifica:

- Identificadores UUID válidos.
- Importes representados mediante Decimal.
- Importes positivos y finitos.
- Importes con un máximo de dos decimales.
- Existencia de fondos disponibles para retiros y bloqueos.
- Existencia de fondos bloqueados para liberaciones y consumos.

## 8. Pruebas de integración

Archivo:

    tests/test_integracion_postgresql.py

Se implementaron diez pruebas que verifican:

1. Depósito y consulta de saldo.
2. Retiro de fondos.
3. Bloqueo de fondos.
4. Liberación de fondos.
5. Consumo de fondos.
6. Rechazo por saldo insuficiente.
7. Idempotencia.
8. Rechazo de operaciones repetidas con importes diferentes.
9. Rollback ante errores.
10. Consulta de portafolios inexistentes.

Resultado de GitHub Actions:

    10 passed

Las pruebas se ejecutaron contra un servidor PostgreSQL real
inicializado con el esquema del proyecto.

## 9. Integración continua

Workflow:

    .github/workflows/test-postgresql.yml

GitHub Actions realiza los siguientes pasos:

1. Levanta PostgreSQL 16.
2. Configura Python 3.11.
3. Instala las dependencias.
4. Inicializa el esquema SQL.
5. Ejecuta las diez pruebas de integración.

El workflow se ejecuta ante cambios enviados a
feature/postgresql y Pull Requests hacia develop.

## 10. Integración con las operaciones de trading

PostgreSQL proporciona las operaciones financieras
necesarias para los procesos de compra y cancelación.

Por ejemplo, una compra puede requerir:

1. Bloquear los fondos necesarios.
2. Registrar y procesar la orden.
3. Consumir los fondos cuando se ejecuta la compra.
4. Liberar los fondos correspondientes si se cancela.

La coordinación entre PostgreSQL y MongoDB debe
realizarse mediante las sagas de la aplicación.

Las transacciones ACID de PostgreSQL no constituyen
por sí solas una transacción distribuida entre las
cuatro bases de datos.
