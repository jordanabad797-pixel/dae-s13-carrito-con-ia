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
