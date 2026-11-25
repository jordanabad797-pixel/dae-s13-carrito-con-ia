# Informe del laboratorio — Extra S13: El carrito revisado por pruebas

**Curso:** Desarrollo de Aplicaciones Empresariales · **Sección:** C24-4-B · **Periodo:** 2026-2

**Integrantes**

| Integrante | Rol principal |
|---|---|
| Abad Mejia, Jordan Alonso | Carrito del equipo (`shop/cart_team.py`), API y pruebas |
| Chavez Campos, Farid Jasir | Revisión del carrito de la IA (`shop/cart_ai.py`), auditoría y compuerta |

Las salidas completas de cada comando están en [`docs/evidencias/`](evidencias/).

---

## Paso 1 — Puesta en marcha y reglas de la tienda

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_shop      # Catálogo cargado: 8 productos.
python manage.py test
```

**Las reglas con nuestras palabras**

| Regla | Lo que entendemos |
|---|---|
| Dinero | Todo importe se guarda y se calcula con `Decimal`; un `float` es binario y no representa exactamente céntimos como 0,35 o 0,845. Se redondea a dos decimales con *half up*: la mitad (0,005) sube. |
| Precio | El único que conoce el precio es el catálogo (la base de datos). El cliente solo dice *qué* y *cuánto*; si mandara un precio, se ignora. |
| Cantidad | Siempre un entero ≥ 1. Quitar más de lo que hay no deja negativos: la línea desaparece. |
| Existencias | Lo que ya está en el carrito **más** lo nuevo no puede superar el stock. Al pagar se vuelve a comprobar, porque el stock pudo cambiar; nunca baja de cero. |
| Cupón | Un solo cupón por carrito. `BIENVENIDA10` = 10 % del subtotal y `MENOS20` = S/ 20 sin superar el subtotal. Aplicar otro (o el mismo) reemplaza al anterior, nunca se suma. |
| Totales | `subtotal = Σ precio × cantidad`; `igv = 18 % × (subtotal − descuento)`; `total = (subtotal − descuento) + igv`; cada parte redondeada por separado. |

**Resumen de la primera ejecución** (`docs/evidencias/01-test-inicial.txt`):

```
Ran 67 tests in 0.066s
FAILED (failures=2, errors=67)
```

Pasan 7 pruebas, todas de `shop/tests/test_audit.py` (las que no usan `--replay`). Pasan porque la
auditoría **no depende de nuestro carrito**: `shop/audit.py` recalcula los totales con
`reference_totals()` de `shop/domain.py` y compara contra el catálogo. Solo las dos pruebas con
`replay=True` necesitan un `Cart` funcionando, y por eso fallan (`REPLAY_UNAVAILABLE`). El resto de
errores son `NotImplementedError` de los `TODO` del esqueleto (los subtests cuentan como errores
separados, por eso hay más errores que pruebas).

## Paso 2 — Lectura de `domain.py`, `cart_team.py` e `impl.py`

**¿Por qué el carrito trabaja con un catálogo de datos puros y no con el modelo de Django?**
El carrito recibe un `dict sku → Product` (un `dataclass` de `shop/domain.py`), no consultas del ORM.
Así la lógica de negocio queda **desacoplada** de la base de datos: las pruebas de líneas, existencias,
totales y cupones son `unittest.TestCase` puros que corren en milisegundos, el mismo carrito sirve a la
API, a la auditoría (`--catalogo-fijo`) y a la compuerta, y se pueden enchufar tres implementaciones
(team, ai, solutions) con el mismo contrato. La traducción ORM ↔ dataclass vive solo en `shop/catalog.py`.

**¿Qué guarda `_qty` y por qué el precio no se guarda en el carrito?**
`_qty` es un `dict sku → cantidad` (en orden de inserción). Solo guarda **qué** y **cuánto**. El precio
se lee del catálogo cada vez que se calculan las líneas: si se guardara en el carrito (y en la sesión)
podría quedar desactualizado o, peor, venir manipulado por el cliente. Una sola fuente de verdad para el
precio = el servidor.

**¿Qué hace `shop/impl.py` con `SHOP_MODE`?**
Lee la variable de entorno `SHOP_MODE` (por defecto `team`) y con `importlib.import_module` carga
`shop.cart_team`, `shop.cart_ai` o `teacher.solutions.cart`. Las pruebas, la API y la auditoría usan
`from shop.impl import cart`, de modo que **el mismo código y las mismas pruebas** se ejecutan contra la
implementación elegida (patrón *Strategy* por configuración). Un modo desconocido o ausente lanza
`RuntimeError`.

## Paso 3 — Líneas: `add`, `remove`, `lines` y validación

Se agregaron dos *helpers* privados: `_check_qty` (entero real ≥ 1; `bool` se rechaza aparte porque
en Python `True` es un `int`) y `_product` (lanza `UnknownProduct`). `lines()` construye cada `Line`
con el **precio del catálogo** en el orden de inserción de `_qty`.

`python manage.py test shop.tests.test_lines` → 12 de 15 pasan. Las 3 restantes llaman a `total()` o
`apply_coupon()`, que son de los pasos 6 y 7 (se ponen en verde allí; ver `evidencias/03-test-lines.txt`).

**¿Por qué `remove` borra la línea cuando la cantidad llega a cero?** Una línea con cantidad 0 no
representa nada que se vaya a comprar: ensucia `lines()`, el resumen y la API, y en el pago intentaría
descontar 0 unidades. Por eso `left <= 0` elimina la clave de `_qty`; así “quitar 5 cuando hay 2” deja la
línea fuera y nunca un número negativo.

**¿Qué ocurriría con el total si quedara una cantidad negativa?** `Line.total = unit_price × qty` sería
negativo y **restaría** al subtotal: con un teclado (189,00) y −3 mouse (−119,70) el subtotal sería 69,30,
es decir, el cliente se llevaría el teclado pagando un tercio. Es exactamente el carrito
`carts/04-cantidad-negativa.json`. Además, en el pago `stock -= qty` **aumentaría** el stock.

## Paso 4 — Existencias acumuladas y pago (`checkout`)

`add` ahora calcula `wanted = qty_of(sku) + qty` y compara **ese** número con el stock; si no alcanza,
lanza `OutOfStock` sin tocar `_qty`. `checkout` trabaja en **dos fases**: primero valida todas las
líneas contra el stock actual y, solo si todas caben, resta el stock, vacía el carrito y borra el cupón.

`python manage.py test shop.tests.test_stock` → 7 de 10 pasan; las 3 restantes necesitan `summary()` y
`apply_coupon()` (pasos 6 y 7). Ver `evidencias/04-test-stock.txt`.

**¿Por qué el pago comprueba otra vez las existencias si `add` ya lo hizo?** Porque entre el `add` y el
`checkout` pasa tiempo y el catálogo es compartido: otro cliente pudo pagar las mismas unidades, o el
administrador corrigió el stock. La comprobación de `add` es una foto del pasado; la del pago es la única
que vale para mover el inventario. La prueba `test_checkout_checks_the_stock_again` simula justo eso.

**¿Qué pasaría si dos clientes pagan las últimas unidades al mismo tiempo?** Sin protección, ambos leen
`stock = 2`, ambos validan y ambos restan: se venden 4 unidades que no existen (*race condition*, lectura
y escritura no atómicas). En este proyecto hay tres defensas: (1) la validación en el pago; (2) la vista
`cart_checkout` envuelve lectura y escritura en `transaction.atomic()`; (3) el campo `stock` es
`PositiveIntegerField`, cuyo `CHECK` en la base rechaza un valor negativo como última barrera. En una base
con concurrencia real (PostgreSQL) se añadiría `select_for_update()` o un `UPDATE … SET stock = stock - n
WHERE stock >= n` para que solo uno de los dos gane.

## Paso 5 — `float` contra `Decimal`

```
>>> 0.1 + 0.2
0.30000000000000004
>>> Decimal("0.1") + Decimal("0.2")
Decimal('0.3')
>>> round(0.845, 2)
0.84
>>> Decimal("0.845").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
Decimal('0.85')
>>> Decimal(0.845)  # el valor real que guarda el float
0.8449999999999999733546474089962430298328399658203125
```

Un `float` es un número binario de 64 bits (IEEE 754): solo representa exactamente fracciones cuyo
denominador es potencia de 2. 0,845 = 169/200 no lo es, así que se guarda el binario más cercano,
**0,84499999…**, que ya está por debajo de la mitad; por eso `round(0.845, 2)` da 0,84 (además `round`
usa redondeo bancario, *half even*). `Decimal("0.845")` guarda el valor decimal exacto y
`quantize(..., ROUND_HALF_UP)` aplica la regla de la tienda: **al céntimo, la mitad hacia arriba**
(0,005 → 0,01). Es la función `money()` de `shop/domain.py`. Ese céntimo es la diferencia entre el carrito
de la IA y el nuestro en el mousepad con `BIENVENIDA10`.

## Paso 6 — Totales con `Decimal` y el helper `money`

`subtotal`, `discount`, `igv` y `total` devuelven siempre `Decimal` redondeado con `money()`; `summary`
convierte cada importe a texto con `fmt()` (dos decimales), de modo que el JSON nunca lleva un `float`.
`total` suma partes **ya redondeadas** (`(subtotal − descuento) + igv`), así el cliente siempre puede
comprobar que las cifras del recibo cuadran.

`python manage.py test shop.tests.test_totals` → 6 de 10 pasan antes del paso 7; las otras 4 usan
`apply_coupon` y pasan en el paso 7 (ver `evidencias/06-test-totals.txt` y `07-test-coupons.txt`).

**Cálculo a mano: un mousepad (PAD-01, S/ 8,45) con `BIENVENIDA10`**

| Concepto | Operación | Exacto | Redondeado (half up) |
|---|---|---|---|
| Subtotal | 8,45 × 1 | 8,45 | **8,45** |
| Descuento | 8,45 × 10 % | 0,845 | **0,85** |
| Base | 8,45 − 0,85 | 7,60 | 7,60 |
| IGV | 7,60 × 18 % | 1,368 | **1,37** |
| Total | 7,60 + 1,37 | 8,97 | **8,97** |

Coincide con `test_the_discount_rounds_half_up` (`discount == 0.85`, `total == 8.97`). Con `float`, el
descuento sería `round(0.845, 2) = 0.84`.

## Paso 7 — Cupones (`apply_coupon`)

El código se normaliza con `strip().upper()`, se valida contra `COUPONS` (si no existe →
`InvalidCoupon` y el carrito no cambia) y se **asigna** a `self._coupon`. Como es una asignación y no un
`append`, aplicar el mismo cupón dos veces o aplicar otro distinto lo reemplaza. El tope del cupón fijo se
resuelve en `discount()` con `min(amount, subtotal)`.

`python manage.py test shop.tests.test_coupons` → **9/9 OK**. Con esto también quedan en verde
`test_lines` (15/15), `test_stock` (10/10) y `test_totals` (10/10).

**¿Qué ocurre cuando un cliente hace doble clic en «Aplicar cupón»?** El navegador envía dos `POST
/api/cart/coupon/` con el mismo cuerpo. Con nuestra implementación la segunda petición deja el carrito
exactamente igual que la primera (operación **idempotente**): descuento 18,90 sobre el teclado, no 37,80.
**¿Por qué la tienda no debe acumular?** Porque el resultado dependería de cuántas veces llega la
petición (doble clic, reintento de red, botón «atrás») y no de la intención del cliente; con descuentos
apilados un cupón del 10 % aplicado diez veces regalaría el producto. La regla “uno por carrito, el último
reemplaza” es la única que da el mismo total sin importar las repeticiones.

## Paso 8 — La API: `add_from_payload`

```python
def add_from_payload(cart, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("sku"), str):
        raise CartError("El cuerpo debe ser un objeto con el campo «sku» (texto)")
    cart.add(payload["sku"], payload.get("qty", 1))
```

Solo se leen `sku` y `qty`; la validación de la cantidad la hace `add` (`"dos"`, `0`, `2.5` → 400). Un
cuerpo que es una lista (`[1, 2]`) o sin `sku` → `CartError` → 400. La clave `price` del cuerpo **nunca se
lee**: no existe ningún camino por el que llegue al carrito.

`python manage.py test shop.tests.test_api` → **14/14 OK** (ver `evidencias/08-test-api.txt`).

**¿Por qué el precio no puede venir del cliente y qué pasaría si viniera?** Todo lo que llega en una
petición HTTP lo controla el cliente: basta abrir las herramientas del navegador, `curl` o Postman para
mandar `{"sku": "LAP-01", "price": 0.01}`. Si el servidor confiara en ese campo, una laptop de
S/ 2 499,90 se vendería a un céntimo (o con precio negativo, la tienda **pagaría** al cliente). Es una
vulnerabilidad de manipulación de parámetros (*OWASP A04 – Insecure Design / Business Logic*). El precio
es dato del servidor: se lee del catálogo en cada cálculo.

## Paso 9 — La API a mano y la suite completa

Con `python manage.py runserver` levantado, tres llamadas de la tabla del README con
`Invoke-RestMethod` (la sesión del carrito viaja en la cookie que guarda `-SessionVariable`):

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/cart/items/" -ContentType "application/json" -Body '{"sku": "KEY-01", "qty": 1}' -SessionVariable shop
# → 201  subtotal 189.00, igv 34.02, total 223.02
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/cart/coupon/" -ContentType "application/json" -Body '{"code": "bienvenida10"}' -WebSession $shop
# → 200  coupon BIENVENIDA10, discount 18.90, igv 30.62, total 200.72
Invoke-WebRequest -Method Post -Uri "http://127.0.0.1:8000/api/cart/checkout/" -ContentType "application/json" -Body '{}' -WebSession $shop
# → 201  el pedido; el stock de KEY-01 baja de 5 a 4 y el carrito queda vacío
```

Respuestas completas en `evidencias/09-api-manual.txt`. Además se probaron los caminos de error con
`curl` (`evidencias/09-api-errores.txt`): precio enviado por el cliente (se ignora: la laptop sigue a
2 499,90), stock acumulado (409), producto desconocido (404), cantidad `"dos"` (400), cupón desconocido
(400), quitar de más (200 con carrito vacío) y pagar un carrito vacío (400).

**Suite completa:** `python manage.py test` → `Ran 67 tests … OK` (`evidencias/09-test-completo.txt`).

## Paso 10 — El duelo

```
$ python manage.py duelo
Duelo: las mismas pruebas contra cada carrito
team       tu carrito                 pasan  67   fallan   0
ai         el carrito de la IA        pasan  49   fallan  18
```

`python manage.py duelo --modo ai` (`evidencias/10-duelo-ai.txt`) — las 18 pruebas que fallan,
agrupadas por archivo:

| Archivo | Pruebas que fallan (18) |
|---|---|
| `test_api.py` (6) | `test_the_price_comes_from_the_catalog_not_from_the_client`, `test_a_negative_price_from_the_client_changes_nothing_either`, `test_more_than_the_stock_is_409`, `test_checkout_when_the_stock_changed_is_409_and_keeps_the_cart` (ERROR: `IntegrityError: CHECK constraint failed: stock`), `test_remove_more_than_there_is_leaves_no_negative_line`, `test_the_coupon_is_applied_once_even_if_the_client_repeats_it` |
| `test_stock.py` (4) | `test_the_stock_counts_what_is_already_in_the_cart`, `test_two_adds_cannot_get_around_the_stock`, `test_checkout_checks_the_stock_again`, `test_the_stock_is_never_negative_after_any_sequence` |
| `test_totals.py` (4) | `test_the_discount_rounds_half_up`, `test_a_discount_of_one_and_a_half_cents`, `test_igv_rounds_half_up`, `test_total_is_the_sum_of_its_rounded_parts` |
| `test_coupons.py` (2) | `test_applying_the_same_coupon_twice_discounts_once`, `test_a_second_coupon_replaces_the_first` |
| `test_lines.py` (1) | `test_remove_more_than_there_is_never_leaves_a_negative_quantity` |
| `test_audit.py` (1) | `test_replay_of_the_rounding_cart_matches_your_cart` |

## Paso 11 — Clasificación de los cinco fallos de `shop/cart_ai.py`

| # | Fallo | Archivo y línea | Prueba que lo detecta | Mensaje / diferencia | Causa | ¿Se vería a mano? |
|---|---|---|---|---|---|---|
| 1 | Redondeo con flotantes | `cart_ai.py:14` `IGV = 0.18`; `:17-18` `_money` = `Decimal(str(round(value, 2)))`; `:84` `float(l.unit_price) * l.qty`; `:88-94` descuento en `float` | `test_totals`: `test_the_discount_rounds_half_up`, `test_a_discount_of_one_and_a_half_cents`, `test_igv_rounds_half_up`, `test_total_is_the_sum_of_its_rounded_parts`; `test_audit`: `test_replay_of_the_rounding_cart…` | `Decimal('0.84') != Decimal('0.85')`; `0.1 != 0.11`; `452.2 != 452.21`; `71.63 != 71.64` | El dinero se convierte a `float` (binario, inexacto) y `round()` usa *half even* sobre un valor que ya es 0,8449…; el resultado se pasa luego a `Decimal`, demasiado tarde | Casi nunca: es un céntimo y solo cuando el tercer decimal exacto es 5 (mousepad con 10 %). Se ve al cuadrar la caja, al comparar con la factura electrónica o con muchas ventas |
| 2 | Precio tomado del cliente **(fallo de seguridad)** | `cart_ai.py:45` `def add(self, sku, qty=1, price=None)`; `:53` `self._prices[sku] = Decimal(str(price)) if price …`; `:139` `cart.add(…, payload.get("price"))`; `:34` guarda los precios en la sesión | `test_api`: `test_the_price_comes_from_the_catalog_not_from_the_client`, `test_a_negative_price_from_the_client_changes_nothing_either` | `'0.01' != '2499.90'`; subtotal `'-100.00' != '2499.90'` | El cuerpo de la petición (dato no confiable) decide el precio | **No**: la pantalla de la tienda nunca manda `price`. **Solo se ve con la API** (curl, Postman, DevTools). Es manipulación de parámetros: una laptop a S/ 0,01 o un precio negativo |
| 3 | Existencias que no cuentan lo ya agregado | `cart_ai.py:50` `if qty > product.stock` (compara solo lo nuevo); `:128-129` `checkout` resta sin volver a comprobar | `test_stock`: `test_the_stock_counts_what_is_already_in_the_cart`, `test_two_adds_cannot_get_around_the_stock`, `test_checkout_checks_the_stock_again`, `test_the_stock_is_never_negative_after_any_sequence`; `test_api`: `test_more_than_the_stock_is_409`, `test_checkout_when_the_stock_changed…` | `OutOfStock not raised`; `-2 not greater than or equal to 0`; `201 != 409`; `IntegrityError: CHECK constraint failed: stock` | La regla “carrito + nuevo ≤ stock” se valida por petición y no por carrito; el pago confía en la validación vieja | Sí, con un producto de poco stock: agregar 2 mousepads y luego 1 más (o 2 + 2) en dos clics. Se nota después: se vende lo que no hay |
| 4 | Cantidad negativa al quitar | `cart_ai.py:63` `self._qty[sku] -= qty`; `:64` `if self._qty[sku] == 0` (no contempla < 0) | `test_lines`: `test_remove_more_than_there_is_never_leaves_a_negative_quantity`; `test_api`: `test_remove_more_than_there_is_leaves_no_negative_line` | `-3 != 0`; `lines` contiene MOU-01 con qty −3 en vez de `[]` | Resta sin piso; solo borra la línea si queda exactamente en 0 | Solo si la pantalla deja escribir cuántas quitar (o con `DELETE …?qty=5`). La línea negativa resta dinero del total y al pagar **sube** el stock |
| 5 | Descuento acumulado dos veces | `cart_ai.py:31` `self._coupons = []`; `:81` `self._coupons.append(code)`; `:89-94` suma un descuento por cada cupón | `test_coupons`: `test_applying_the_same_coupon_twice_discounts_once`, `test_a_second_coupon_replaces_the_first`; `test_api`: `test_the_coupon_is_applied_once_even_if_the_client_repeats_it` | `Decimal('37.8') != Decimal('18.90')`; `38.9 != 20.00`; `'37.80' != '18.90'` | Lista de cupones en lugar de un solo cupón; aplicar no es idempotente | Sí: doble clic en «Aplicar cupón», reintento de red o volver a aplicar otro código |

- **Fallo de seguridad:** el #2 (precio del cliente). Los demás son errores de lógica que hacen perder
  dinero, pero el #2 lo **explota a voluntad** un atacante.
- **Solo se ve con la API:** el #2. Un cliente que usa la interfaz jamás envía el precio; hace falta
  construir la petición a mano.

## Paso 12 — Las cuatro preguntas de revisión aplicadas a `cart_ai.py`

| Pregunta | Respuesta | Línea que lo demuestra |
|---|---|---|
| 1. ¿Todo el dinero es `Decimal` de principio a fin, con *half up*? | **No** | `:14 IGV = 0.18`, `:18 return Decimal(str(round(value, 2)))`, `:84 sum(float(l.unit_price) * l.qty …)`, `:88 total_discount = 0.0` |
| 2. ¿El servidor es la única fuente del precio? | **No** | `:139 cart.add(payload["sku"], payload.get("qty", 1), payload.get("price"))` y `:53 self._prices[sku] = Decimal(str(price)) if price is not None else product.price` |
| 3. ¿Cada regla de cantidad y existencias se cumple con cualquier secuencia? | **No** | `:50 if qty > product.stock:` (ignora lo que ya hay), `:63 self._qty[sku] -= qty` (puede quedar negativo), `:128-129` resta sin revalidar |
| 4. ¿Repetir una acción da el mismo resultado? | **No** | `:81 self._coupons.append(code)`: cada repetición agrega otro descuento |
