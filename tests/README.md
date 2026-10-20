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
