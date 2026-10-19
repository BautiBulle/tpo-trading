# Redis - Cotizaciones vigentes

## 1. Objetivo

Redis se utiliza para almacenar y consultar las cotizaciones
vigentes de los instrumentos financieros de la plataforma de trading.

Dentro de la arquitectura de persistencia políglota, Redis
es responsable de los precios actuales, mientras que Cassandra
almacena el historial de cotizaciones.

## 2. Modelo de datos

Cada instrumento financiero se representa mediante un hash de Redis.

Formato de clave:

    precio:{simbolo}

Ejemplo:

    precio:AAPL

Campos almacenados:

| Campo | Descripción |
|---|---|
| compra | Precio de compra |
| venta | Precio de venta |
| ultimo | Último precio registrado |
| fechaHora | Fecha y hora de la cotización en UTC |
| timestamp_ns | Campo interno para ordenar actualizaciones |

Los precios se almacenan como cadenas decimales para evitar
pérdidas de precisión por el uso de números de punto flotante.

El campo `timestamp_ns` contiene un valor ordenable calculado
a partir del instante UTC con precisión de microsegundos.
Aunque el nombre del campo incluye `ns`, su precisión es
de microsegundos.

## 3. Operaciones implementadas

Archivo:

    app/repos/precios_redis.py

### set_precio()

Recibe:

- Símbolo del instrumento.
- Precio de compra.
- Precio de venta.
- Último precio.
- Fecha y hora de la cotización.

Valida que el símbolo no esté vacío, que los precios sean
valores Decimal finitos y no negativos, y que la fecha
incluya zona horaria.

Normaliza la fecha a UTC antes de almacenar la cotización.

### get_precio()

Consulta el hash correspondiente al instrumento.

Devuelve los precios como Decimal y la fecha como datetime.

Si no existe una cotización, devuelve None.

## 4. Protección contra cotizaciones antiguas

Las cotizaciones pueden llegar fuera de orden.

Para evitar que una cotización antigua sobrescriba una
más reciente, la actualización se realiza mediante
un script Lua ejecutado en Redis.

El script compara el timestamp recibido con el almacenado:

- Si no existe una cotización anterior, guarda la nueva.
- Si la nueva cotización es posterior, actualiza el hash.
- Si la nueva cotización es anterior o tiene el mismo
  timestamp, conserva la cotización existente.

La comparación y la escritura se ejecutan atómicamente,
evitando condiciones de carrera entre actualizaciones.

## 5. Persistencia

El servicio Redis se configura en Docker Compose con
Append Only File (AOF) habilitado.

Esto permite registrar operaciones de escritura para
facilitar la recuperación de datos tras un reinicio.

La configuración de persistencia no sustituye los
mecanismos de respaldo ni garantiza por sí sola
ausencia absoluta de pérdida de datos.

## 6. Pruebas automatizadas

Pruebas unitarias:

    tests/test_precios_redis.py

Pruebas de integración:

    tests/test_integracion_redis.py

Las pruebas verifican:

- Escritura y lectura de cotizaciones.
- Conversión de precios a Decimal.
- Validación de símbolos, precios y fechas.
- Normalización de fechas a UTC.
- Actualización con una cotización más reciente.
- Rechazo de cotizaciones antiguas.
- Conservación de la primera cotización cuando
  dos actualizaciones tienen el mismo timestamp.
- Consulta de instrumentos sin cotización.

Las pruebas de integración utilizan un servidor Redis real
y eliminan las claves temporales utilizadas.

## 7. Integración continua

Workflow:

    .github/workflows/test-redis.yml

GitHub Actions inicia un servicio Redis 7, instala las
dependencias de Python y ejecuta las pruebas unitarias
y de integración.

El workflow se ejecuta ante cambios enviados a
feature/redis y mediante Pull Requests hacia develop.

## 8. Rol dentro de la plataforma

Redis resuelve la consulta rápida del precio vigente
de cada instrumento.

La integración con el flujo general de cotizaciones
debe coordinar la actualización del precio vigente
en Redis con el almacenamiento histórico en Cassandra.

Redis no se utiliza para registrar saldos financieros
ni para reemplazar las transacciones ACID de PostgreSQL.
