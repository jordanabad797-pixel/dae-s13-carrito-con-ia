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
