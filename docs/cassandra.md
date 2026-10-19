# Apache Cassandra — Historial de cotizaciones, operaciones y auditoría

## 1. Objetivo y justificación

Apache Cassandra se utiliza en la plataforma de trading como motor de persistencia NoSQL para almacenar información histórica de cotizaciones, operaciones ejecutadas y eventos de auditoría.

La elección de Cassandra responde a su capacidad para gestionar grandes volúmenes de escrituras y organizar los datos mediante un modelo distribuido orientado a consultas específicas.

Dentro de la arquitectura de persistencia políglota, cada tecnología cumple una responsabilidad diferente:

- **PostgreSQL:** saldos, reservas de fondos y movimientos financieros que requieren transacciones ACID.
- **MongoDB:** usuarios, carteras, instrumentos, órdenes y seguimiento de sagas.
- **Redis:** cotizaciones vigentes de los instrumentos financieros.
- **Cassandra:** cotizaciones históricas, historial de operaciones y auditoría.

Esta separación permite utilizar cada motor de base de datos según las características de la información y las necesidades de acceso.

Cassandra no reemplaza las transacciones financieras de PostgreSQL ni representa la fuente autoritativa del estado actual de una orden. Su función principal es conservar información histórica y facilitar consultas de trazabilidad.

## 2. Modelo de datos orientado a consultas

En Cassandra se aplica un enfoque de modelado denominado *query-driven modeling*: las tablas se diseñan a partir de las consultas que necesita resolver la aplicación.

A diferencia del modelado relacional tradicional, donde se busca reducir la redundancia mediante normalización, Cassandra permite duplicar información de forma controlada para responder eficientemente a diferentes patrones de acceso.

Se definió el keyspace `tpo_trading`, con cuatro tablas.

### 2.1. Tabla `historico_cotizacion`

Almacena el historial de precios de los instrumentos financieros.

**Campos principales:**

- `id_instrumento`: identificador del instrumento.
- `dia`: día de la cotización.
- `fecha_hora`: fecha y hora de actualización.
- `precio_compra`: precio de compra.
- `precio_venta`: precio de venta.
- `precio_ultimo`: último precio registrado.
- `volumen`: volumen asociado a la cotización.

**Clave primaria:**

```sql
PRIMARY KEY ((id_instrumento, dia), fecha_hora)
```

La clave de partición está compuesta por `id_instrumento` y `dia`, por lo que las cotizaciones de un instrumento se agrupan por día.

Esto evita concentrar todo el historial de un instrumento en una única partición de crecimiento indefinido.

La columna de clustering `fecha_hora` mantiene los registros ordenados de manera descendente.

**Consultas previstas:** recuperar cotizaciones de un instrumento dentro de un período determinado.

Cuando el período comprende varios días, la aplicación consulta cada partición diaria y reúne los resultados en Python.

**Problemas relacionados:** problema 1, correspondiente al registro histórico de precios, y consultas históricas utilizadas en análisis posteriores.

### 2.2. Tabla `operaciones_por_usuario`

Almacena las operaciones ejecutadas, organizadas por usuario y mes.

**Campos principales:**

- `id_usuario`: identificador del inversor.
- `mes`: período mensual.
- `fecha_hora`: fecha y hora de la operación.
- `id_operacion`: identificador único de la operación.
- `id_instrumento`: instrumento negociado.
- `tipo`: tipo de operación.
- `cantidad`: cantidad ejecutada.
- `precio`: precio de ejecución.
- `importe`: importe total.

**Clave primaria:**

```sql
PRIMARY KEY ((id_usuario, mes), fecha_hora, id_operacion)
```

La clave de partición combina el usuario con el mes, evitando que todas sus operaciones se acumulen en una sola partición.

La combinación de fecha y operación permite ordenar e identificar los registros.

**Consultas previstas:** recuperar el historial de operaciones de un inversor en un período determinado.

**Problemas relacionados:** problema 6, vinculado con el historial y el análisis del rendimiento de la cartera.

### 2.3. Tabla `operaciones_por_instrumento`

Almacena las operaciones ejecutadas desde una perspectiva diferente: el instrumento financiero.

**Campos principales:**

- `id_instrumento`: instrumento negociado.
- `dia`: día de la operación.
- `fecha_hora`: fecha y hora de ejecución.
- `id_operacion`: identificador de la operación.
- `id_usuario`: usuario que realizó la operación.
- `tipo`: tipo de operación.
- `cantidad`: cantidad ejecutada.
- `precio`: precio de ejecución.

**Clave primaria:**

```sql
PRIMARY KEY ((id_instrumento, dia), fecha_hora, id_operacion)
```

La partición combina el instrumento y el día. Esto permite recuperar las operaciones de un instrumento en intervalos temporales específicos.

**Consultas previstas:** analizar operaciones sobre un mismo instrumento, incluyendo la identificación de posibles operaciones relacionadas o espejo.

**Problemas relacionados:** problema 7.

#### Desnormalización controlada

Una operación se registra tanto en `operaciones_por_usuario` como en `operaciones_por_instrumento`.

Esta duplicación es intencional:

- La primera tabla optimiza las consultas por inversor.
- La segunda optimiza las consultas por instrumento.

De esta manera, cada consulta accede a las particiones correspondientes sin necesitar búsquedas generales sobre toda la base de datos.

### 2.4. Tabla `auditoria_por_instrumento`

Almacena eventos de auditoría asociados a instrumentos financieros.

**Campos principales:**

- `id_instrumento`: instrumento afectado.
- `fecha_hora`: fecha y hora del evento.
- `id_registro`: identificador del evento.
- `accion`: acción registrada.
- `motivo`: motivo del evento.
- `id_operador`: operador responsable.

**Clave primaria:**

```sql
PRIMARY KEY ((id_instrumento), fecha_hora, id_registro)
```

Esta estructura permite consultar eventos de auditoría por instrumento y rango temporal.

**Consultas previstas:** recuperar eventos relacionados con la suspensión de un instrumento y conservar trazabilidad de las acciones realizadas.

**Problemas relacionados:** problema 8.

**Consideración de escalabilidad:** esta tabla no utiliza particiones temporales. Si un instrumento acumulara un volumen muy elevado de eventos, sería conveniente evaluar una partición adicional por período.

## 3. Estrategia de consultas sin `ALLOW FILTERING`

Una decisión de diseño fundamental fue evitar el uso de `ALLOW FILTERING`.

En Cassandra, una consulta eficiente debe utilizar adecuadamente la clave de partición y, cuando corresponde, las columnas de clustering.

Por este motivo:

1. Las cotizaciones se consultan por instrumento y día.
2. Las operaciones por usuario se consultan por usuario y mes.
3. Las operaciones por instrumento se consultan por instrumento y día.
4. Los eventos de auditoría se consultan por instrumento y rango de fechas.

Para consultas que abarcan múltiples días o meses, Python determina las particiones temporales necesarias y ejecuta las consultas correspondientes.

Los resultados se reúnen y ordenan en la aplicación.

Este enfoque permite consultar los datos sin recurrir a filtrados generales del lado del servidor.

## 4. Implementación en Python

La lógica de acceso a Cassandra se centralizó en el archivo:

`app/repos/historial_cass.py`

Se utiliza la biblioteca `cassandra-driver` y la función de conexión `get_cassandra()` definida en `app/config.py`.

Se implementaron siete funciones principales:

| Función | Responsabilidad |
|---|---|
| `registrar_precio()` | Registrar una cotización histórica |
| `consultar_precios()` | Recuperar cotizaciones por instrumento y período |
| `registrar_operacion()` | Registrar una operación en las dos tablas de historial |
| `consultar_operaciones_usuario()` | Consultar operaciones por inversor |
| `consultar_operaciones_instrumento()` | Consultar operaciones por instrumento |
| `registrar_auditoria()` | Registrar un evento de auditoría |
| `consultar_auditoria()` | Consultar eventos de auditoría por instrumento |

### 4.1. Consultas preparadas

Las operaciones de acceso a Cassandra utilizan consultas preparadas (*prepared statements*) con parámetros vinculados.

Esto permite separar la estructura de las consultas de los valores enviados y facilita su reutilización.

### 4.2. Manejo de fechas

La implementación utiliza fechas normalizadas a UTC.

Las funciones validan que las fechas recibidas incluyan información de zona horaria, evitando ambigüedades al consultar datos históricos.

Los intervalos de consulta se manejan mediante límites temporales definidos, y las particiones se determinan según el día o mes correspondiente.

### 4.3. Manejo de valores monetarios

Los precios, cantidades e importes se representan mediante `Decimal`, evitando los problemas de precisión asociados al uso de números de punto flotante para valores financieros.

Los campos correspondientes se almacenan utilizando el tipo `decimal` de Cassandra.

## 5. Consistencia e idempotencia

Cassandra almacena información histórica que puede ser escrita como consecuencia de operaciones coordinadas por otros componentes.

En particular, `registrar_operacion()` debe persistir una misma ejecución en dos tablas diferentes.

Estas escrituras no constituyen una transacción ACID conjunta entre ambas tablas. Por lo tanto, una falla entre las inserciones podría dejar temporalmente un registro en una sola de ellas.

Para facilitar los reintentos, se conserva el identificador de la operación y sus datos originales.

Repetir una inserción utilizando la misma clave primaria permite actualizar la misma fila en lugar de generar otra con una clave diferente.

Sin embargo, esto no garantiza por sí solo la recuperación automática ante fallas parciales.

La coordinación de reintentos, compensaciones y recuperación de operaciones incompletas corresponde al orquestador de sagas de la plataforma.

En el caso de los registros de auditoría, también resulta necesario conservar el mismo identificador del evento durante los reintentos.

## 6. Configuración y despliegue

Cassandra se despliega mediante Docker Compose utilizando la imagen:

`cassandra:4.1`

La configuración incluye:

- Puerto de conexión CQL: `9042`.
- Volumen persistente para los datos.
- Healthcheck para verificar la disponibilidad del servicio.
- Configuración de memoria para facilitar su ejecución en entornos de desarrollo.

Se dispone de un servicio adicional denominado `cassandra-init`, encargado de ejecutar el script:

`init/cassandra.cql`

Este archivo crea el keyspace `tpo_trading` y las cuatro tablas de historial y auditoría.

La inicialización se ejecuta después de que Cassandra se encuentra disponible.

## 7. Pruebas y validación

Se implementaron pruebas automáticas utilizando `pytest` y GitHub Actions.

El workflow se encuentra definido en:

`.github/workflows/test-cassandra.yml`

### 7.1. Pruebas unitarias

Se desarrollaron nueve pruebas en:

`tests/test_historial_cass.py`

Estas pruebas utilizan una sesión simulada de Cassandra y verifican el comportamiento de las funciones del repositorio, los parámetros enviados y distintas validaciones.

**Resultado:** 9 pruebas aprobadas.

### 7.2. Pruebas de integración

Se desarrollaron tres pruebas en:

`tests/test_integracion_cassandra.py`

A diferencia de las pruebas unitarias, estas utilizan una instancia real de Cassandra 4.1 iniciada mediante Docker.

Se verificaron tres escenarios:

**Cotizaciones históricas:** inserción de una cotización y posterior recuperación del precio registrado.

**Operaciones:** registro de una operación y recuperación desde las tablas `operaciones_por_usuario` y `operaciones_por_instrumento`.

**Auditoría:** registro de un evento de suspensión y posterior recuperación mediante una consulta histórica.

**Resultado:** 3 pruebas aprobadas.

### 7.3. Resultados obtenidos

| Tipo de prueba | Cantidad | Resultado |
|---|---:|---|
| Unitarias | 9 | Aprobadas |
| Integración | 3 | Aprobadas |
| **Total** | **12** | **12 aprobadas, 0 fallidas** |

Las pruebas de integración se ejecutaron correctamente mediante GitHub Actions, utilizando Python 3.11 y una instancia real de Cassandra.

La ejecución completa del trabajo de integración finalizó en aproximadamente 1 minuto y 43 segundos.

El Pull Request #1 integró el módulo Cassandra en la rama `develop` después de superar las verificaciones automáticas.

## 8. Relación con los problemas del trabajo práctico

| Problema | Participación de Cassandra |
|---|---|
| 1. Cotizaciones | Persistencia histórica de precios |
| 3. Ejecución de órdenes | Registro histórico de operaciones ejecutadas |
| 6. Historial y rendimiento | Consulta de operaciones y datos históricos |
| 7. Análisis de operaciones | Consulta de operaciones por instrumento |
| 8. Suspensión de instrumentos | Registro y consulta de auditoría |

Cassandra actúa como repositorio histórico. Las reglas de negocio y la coordinación entre bases de datos permanecen a cargo de los componentes de aplicación correspondientes.

## 9. Alcance y trabajo pendiente

El módulo de acceso a Cassandra fue implementado y validado mediante pruebas unitarias y pruebas básicas de integración.

Se comprobó que es posible registrar y recuperar cotizaciones, operaciones y eventos de auditoría utilizando el esquema definido.

No obstante, todavía quedan pendientes las siguientes tareas a nivel de plataforma:

- Integrar las funciones del repositorio con el orquestador de sagas.
- Coordinar los registros históricos con los cambios realizados en PostgreSQL y MongoDB.
- Validar escenarios de fallas parciales y reintentos entre distintos motores.
- Comprobar el comportamiento del sistema con el volumen de datos requerido por el trabajo práctico.
- Verificar los flujos completos de ejecución, análisis y suspensión de instrumentos.

Por lo tanto, las pruebas realizadas validan el funcionamiento básico del módulo Cassandra, pero no constituyen una validación integral de toda la plataforma de trading.

## 10. Conclusión

La implementación de Cassandra permite incorporar almacenamiento histórico especializado dentro de la arquitectura de persistencia políglota.

El modelo orientado a consultas, la partición temporal de cotizaciones y operaciones, y la desnormalización controlada permiten resolver diferentes patrones de acceso sin utilizar `ALLOW FILTERING`.

Las pruebas unitarias y de integración aportan evidencia del funcionamiento del repositorio y de su compatibilidad con una instancia real de Cassandra.

El siguiente objetivo es integrar este componente con los demás motores y con el orquestador de sagas para validar el funcionamiento completo de la plataforma.
