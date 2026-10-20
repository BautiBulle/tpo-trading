Un test por falla demostrable.

## Problema 4: cancelación y expiración

Implementación: `app/problemas/p4_cancelacion.py`. Sigue las secciones 6 y 7
del plan de la Etapa 2: cambiar el estado en MongoDB, liberar la reserva en
PostgreSQL, registrar los pasos y compensar si falla la operación.

```python
from uuid import UUID, uuid4
from app.problemas.p4_cancelacion import (
    cancelar_orden, expirar_orden, expirar_ordenes,
)

# Usar el UUID de una orden real pendiente o parcialmente ejecutada.
id_orden = UUID("00000000-0000-0000-0000-000000000001")
id_cancelacion = uuid4()
orden = cancelar_orden(id_orden, id_cancelacion)

# Alternativas para vencimientos; no se aplican a la orden ya cancelada.
# expirar_orden(id_otra_orden)
# resultado = expirar_ordenes()
```

El vencimiento utiliza `fechaExpiracion`, que se establece con el parámetro
`fecha_expiracion` de `app.repos.mongo_repo.crear_orden`. Las fechas deben tener
zona horaria; una orden vence cuando su fecha es menor o igual a la evaluada.
`expirar_ordenes()` devuelve `{"vencidas": [...], "errores": [...]}`. Se ejecuta
cuando lo llama la aplicación; no hay un planificador automático.

Se admiten compras `PENDIENTE`, `PARCIALMENTE_EJECUTADA` y el estado local
`PARCIAL`. Las ejecuciones confirmadas y sus posiciones e historiales se conservan.
La reserva restante se calcula con los movimientos de esa orden, para no liberar
fondos de otras órdenes ni perder centavos por redondeos de ejecuciones parciales.

El estado temporal `EN_CANCELACION` impide comenzar otra ejecución o cierre.
Si ya hay una ejecución reservada, se rechaza el cierre sin liberar dinero.
La orden y la saga se confirman juntas en una transacción MongoDB. Repetir un
cierre completado no vuelve a liberar fondos; reutilizar su UUID para otra orden
se rechaza.

Para demostrar compensaciones, pasar `forzar_falla="ORDEN"` o
`forzar_falla="SALDO"`. Si falla un paso, se vuelve a reservar el dinero antes
de restaurar el estado original. Si la compensación falla, la saga queda en
`REQUIERE_REVISION` y la orden sigue tomada. Una saga compensada necesita un
nuevo `id_cancelacion` para iniciar otro intento; una pendiente o que requiere
revisión necesita intervención, no se reanuda automáticamente.

```powershell
# Unitarias, sin bases levantadas.
.\.venv\Scripts\python.exe -m pytest tests/test_p4_cancelacion.py -v

# Integración con Docker levantado: incluye el flujo P2 -> P3 -> P4.
$env:RUN_P4_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_integracion_p4.py -v
Remove-Item Env:RUN_P4_INTEGRATION
```

La integración crea bases temporales en PostgreSQL y MongoDB y un keyspace
temporal en Cassandra para comprobar también las ejecuciones del P3. Los elimina
al terminar y limpia la clave Redis que usa para probar el P2. No requiere cargar
el seed ni modificar el esquema de las bases de trabajo. La cuenta de PostgreSQL
de Docker tiene los permisos necesarios para crear la base temporal.

El workflow `.github/workflows/test-problema-4.yml` ejecuta las pruebas unitarias
y de integración en los pushes a `feature/problema-4` y en los PR hacia `develop`.

## Problema 5: valor actual del portafolio

Implementación: `app/problemas/p5_valor_portafolio.py`. Según la sección 6 del
plan de la Etapa 2, consulta las posiciones en MongoDB y los precios en Redis:

```text
valor de cada posición = cantidad × último precio
valor total = suma de los valores de las posiciones
```

Se conserva la estructura del P3 implementado: `aplicar_compra()` escribe en
la colección `posiciones`, y `listar_posiciones_portafolio()` consulta esa misma
colección por `idPortafolio`. El PDF proponía posiciones embebidas en el documento
del portafolio; ese arreglo permanece vacío en el flujo actual del P3. Leer la
colección usada por el P3 permite valorar sus ejecuciones sin duplicar datos.

Con el UUID de un portafolio existente:

```python
from app.problemas.p5_valor_portafolio import calcular_valor_portafolio

resultado = calcular_valor_portafolio(id_portafolio)
print(resultado["valorTotal"])
for posicion in resultado["posiciones"]:
    print(posicion["simbolo"], posicion["cantidad"], posicion["valorActual"])
```

El resultado contiene `idPortafolio`, `valorTotal`, `posiciones` y `fechaConsulta`.
Cada posición incluye el identificador y símbolo del instrumento, la cantidad,
el `precioActual`, su `valorActual` y `fechaCotizacion`.

Se usa el campo `ultimo` de Redis como precio de valuación. Los cálculos usan
`Decimal` y conservan las fracciones, sin redondear a centavos durante la suma.
El total representa las tenencias; el efectivo disponible o bloqueado de
PostgreSQL no forma parte de esta consulta del PDF.

Un portafolio vacío vale cero. Las posiciones en cero que deja una compensación
del P3 se omiten. Un instrumento suspendido sigue siendo una tenencia y se valora
con su última cotización. Si falta un instrumento o un precio para una cantidad
positiva, se informa el error; no se entrega un total incompleto.

La consulta no escribe datos ni necesita una saga. En cada llamada vuelve a leer
las posiciones y los precios. Las fechas devueltas permiten identificar cuándo
se consultó y a qué instante corresponde cada cotización; las lecturas entre
MongoDB y Redis no constituyen una instantánea atómica.

```powershell
# Pruebas unitarias, sin bases.
.\.venv\Scripts\python.exe -m pytest tests/test_p5_valor_portafolio.py -v

# Integración: solo requiere MongoDB y Redis levantados.
$env:RUN_P5_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_integracion_p5.py -v
Remove-Item Env:RUN_P5_INTEGRATION
```

La integración utiliza una base MongoDB temporal y claves Redis con símbolos
únicos. Elimina ambos al terminar. El flujo real P2 -> P3 -> P4 de
`tests/test_integracion_p4.py` también verifica la valuación del P5 antes y
después de cancelar la parte pendiente de una orden.

## Problema 6: historial y rendimiento

Implementación: `app/problemas/p6_historial.py`, según la sección 6 del plan de
la Etapa 2. MongoDB verifica el usuario y resuelve el UUID del instrumento al
símbolo que el P3 guarda en Cassandra. Cassandra aporta las operaciones por
usuario y mes; el filtro opcional por instrumento se aplica a esos resultados.

```python
from datetime import datetime, timezone
from app.problemas.p6_historial import (
    consultar_historial, calcular_rendimiento_12_meses,
)

# id_usuario e id_instrumento deben ser UUID existentes en MongoDB.
desde = datetime(2025, 10, 20, tzinfo=timezone.utc)
hasta = datetime(2026, 10, 20, tzinfo=timezone.utc)
operaciones = consultar_historial(id_usuario, desde, hasta)
# Para consultar solamente un instrumento:
# operaciones = consultar_historial(id_usuario, desde, hasta, id_instrumento)

resultado = calcular_rendimiento_12_meses(id_usuario, fecha_actual=hasta)
print(resultado["gananciaRealizada"])
print(resultado["rendimientoPorcentual"])
```

El historial devuelve una lista ordenada por fecha con `idOperacion`, `idUsuario`,
`simbolo`, `fechaHora`, `tipo`, `cantidad`, `precio` e `importe`. Las fechas de
entrada requieren zona horaria y las de salida están en UTC. Los intervalos
incluyen `desde` y excluyen `hasta`. Un historial vacío devuelve `[]`.
Los instrumentos suspendidos conservan su historial.

El PDF no fija una fórmula de rendimiento. Para esta implementación se eligió
la **ganancia realizada en ventas**, usando costo promedio ponderado:

```text
costo promedio = costo acumulado de la tenencia / cantidad disponible
costo vendido = cantidad vendida × costo promedio anterior a la venta
ganancia realizada = importe de ventas del período − costo vendido del período
rendimiento porcentual = ganancia realizada / costo vendido × 100
```

Ejemplo: comprar 10 unidades a 100 y 10 a 200 deja un costo promedio de 150.
Vender 5 a 180 produce 900 de ingresos, 750 de costo y 150 de ganancia: 20 %.
Las compras que siguen abiertas no son pérdidas y no se valoran en esta consulta.
Si solo hay compras, la ganancia realizada es cero y el porcentaje es `None`,
porque todavía no existe costo vendido. El P3 actual ejecuta compras; las ventas
se prueban registrando operaciones con el repositorio existente de Cassandra.

Se toman doce meses calendario hacia atrás desde `fecha_actual` (por defecto,
ahora en UTC). El 29 de febrero retrocede al 28 de febrero del año anterior.
Para reconstruir el costo, se leen también las operaciones anteriores al período,
desde `fechaCreacion` del usuario. Es necesario conservar ese historial completo,
incluidas las compras iniciales. Las ventas anteriores actualizan la tenencia,
pero su ganancia no se suma al período solicitado.

El resultado incluye `desde`, `hasta`, `metodo`, `cantidadOperaciones`,
`importeCompras`, `importeVentas`, `costoVendido`, `gananciaRealizada`,
`rendimientoPorcentual` y el detalle por símbolo en `instrumentos`.
Los importes usan `Decimal`, sin redondeos intermedios a centavos. El porcentaje
total se calcula sobre el costo total vendido; no es un promedio de porcentajes.
La consulta agrupa todos los portafolios del usuario porque el índice actual de
Cassandra está organizado por usuario, no por portafolio.

No incluye comisiones, impuestos, dividendos ni ganancias de posiciones abiertas.
No escribe datos ni requiere saga. Si hay una venta sin compras suficientes,
datos inválidos o compras y ventas del mismo símbolo con el mismo timestamp,
informa el error en lugar de inventar el costo. Cassandra guarda milisegundos
y no permite reconstruir el orden de esas operaciones simultáneas por su UUID.
Los errores de conexión se propagan; no se devuelven resultados parciales.

```powershell
# Unitarias, sin bases.
.\.venv\Scripts\python.exe -m pytest tests/test_p6_historial.py -v

# Integración: MongoDB y Cassandra levantados.
$env:RUN_P6_INTEGRATION = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_integracion_p6.py -v
Remove-Item Env:RUN_P6_INTEGRATION
```

La integración crea una base MongoDB y un keyspace Cassandra temporales y los
elimina al terminar. Comprueba aislamiento entre usuarios, filtros, cruces de
mes y año, límites del período, ganancias, pérdidas y operaciones compensadas.
El flujo P2 -> P3 -> P4 también verifica que el P6 vea la ejecución del P3.
El workflow `.github/workflows/test-problema-6.yml` ejecuta las pruebas unitarias
y de integración en la rama `feature/problema-6` y en las PR hacia `develop`.
