"""Your cart. Complete every TODO until `python manage.py test` is green.

The rules (money, stock, coupons, checkout) are in README.md and in shop/domain.py. Do not change
shop/domain.py or the tests. Money is Decimal (never float) and the price always comes from the
catalog, never from the request.
"""
from decimal import Decimal  # noqa: F401

from shop.domain import (  # noqa: F401  (you will need most of these)
    COUPONS,
    IGV_RATE,
    CartError,
    InvalidCoupon,
    InvalidQuantity,
    Line,
    OutOfStock,
    UnknownProduct,
    fmt,
    money,
)


class Cart:
    def __init__(self, catalog):
        self._catalog = catalog  # sku -> Product (price Decimal, stock int)
        self._qty = {}  # sku -> quantity, in insertion order
        self._coupon = None  # one coupon per cart

    # --- persistence between requests (already done) ---
    def to_state(self):
        return {"qty": dict(self._qty), "coupon": self._coupon}

    @classmethod
    def from_state(cls, catalog, state):
        cart = cls(catalog)
        cart._qty = {sku: int(q) for sku, q in state.get("qty", {}).items() if sku in catalog}
        cart._coupon = state.get("coupon")
        return cart

    # --- validation helpers ---
    @staticmethod
    def _check_qty(qty):
        """A quantity is a real int >= 1. bool is a subclass of int, so it is rejected explicitly."""
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise InvalidQuantity(f"Cantidad no válida: {qty!r}")

    def _product(self, sku):
        product = self._catalog.get(sku)
        if product is None:
            raise UnknownProduct(f"No existe el producto {sku!r}")
        return product

    # --- lines ---
    def add(self, sku, qty=1):
        """qty is an int >= 1 (InvalidQuantity); the sku exists (UnknownProduct);
        what is already in the cart plus qty must not exceed the stock (OutOfStock, cart unchanged)."""
        self._check_qty(qty)
        product = self._product(sku)
        wanted = self.qty_of(sku) + qty  # count what is ALREADY in the cart, not only the new units
        if wanted > product.stock:
            raise OutOfStock(f"{sku}: tendrías {wanted} y quedan {product.stock}")
        self._qty[sku] = wanted

    def remove(self, sku, qty=None):
        """qty=None removes the whole line; otherwise subtract qty and drop the line when it
        reaches zero. A sku that is not in the cart is UnknownProduct. Never leave a negative quantity."""
        if sku not in self._qty:
            raise UnknownProduct(f"{sku!r} no está en el carrito")
        if qty is None:
            del self._qty[sku]
            return
        self._check_qty(qty)
        left = self._qty[sku] - qty
        if left <= 0:  # removing more than there is empties the line, never a negative quantity
            del self._qty[sku]
        else:
            self._qty[sku] = left

    def qty_of(self, sku):
        return self._qty.get(sku, 0)

    def lines(self):
        """One Line(sku, name, unit_price, qty) per sku, in insertion order, price from the catalog."""
        return [
            Line(sku, self._catalog[sku].name, self._catalog[sku].price, qty)
            for sku, qty in self._qty.items()
        ]

    # --- coupon and totals ---
    def apply_coupon(self, code):
        """TODO: code without spaces and in upper case; unknown -> InvalidCoupon. One coupon per cart:
        applying again (the same or another) REPLACES it."""
        raise NotImplementedError("TODO: apply_coupon")

    def subtotal(self):
        """Sum of price * qty, rounded to cents (Decimal)."""
        return money(sum((line.total for line in self.lines()), Decimal("0")))

    def discount(self):
        """Percent coupon = subtotal * pct / 100 rounded half up; fixed coupon = the amount, but
        never more than the subtotal; no coupon = Decimal('0.00')."""
        if self._coupon is None:
            return money(Decimal("0"))
        kind, amount = COUPONS[self._coupon]
        subtotal = self.subtotal()
        if kind == "percent":
            return money(subtotal * amount / 100)
        return money(min(amount, subtotal))

    def _base(self):
        """Taxable base: what is left after the discount."""
        return self.subtotal() - self.discount()

    def igv(self):
        """18 % of (subtotal - discount), rounded half up."""
        return money(self._base() * IGV_RATE)

    def total(self):
        """(subtotal - discount) + igv: the sum of parts that are already rounded."""
        return money(self._base() + self.igv())

    def summary(self):
        """The dict the API returns: every amount as a 2-decimal string (never a float in JSON)."""
        return {
            "lines": [
                {"sku": line.sku, "name": line.name, "unit_price": fmt(line.unit_price), "qty": line.qty,
                 "line_total": fmt(line.total)}
                for line in self.lines()
            ],
            "coupon": self._coupon,
            "subtotal": fmt(self.subtotal()),
            "discount": fmt(self.discount()),
            "igv": fmt(self.igv()),
            "total": fmt(self.total()),
        }

    # --- checkout ---
    def checkout(self):
        """Empty cart -> CartError; stock is checked AGAIN (OutOfStock); on success the catalog stock
        goes down by what was bought, the cart is emptied and the summary of the order is returned.

        Two phases: first EVERY line is validated, then the stock is lowered. If any line fails nothing
        has changed yet (neither the catalog nor the cart), so the operation is all-or-nothing.
        """
        if not self._qty:
            raise CartError("El carrito está vacío")
        for sku, qty in self._qty.items():  # phase 1: validate everything, touch nothing
            product = self._product(sku)
            if qty > product.stock:
                raise OutOfStock(f"{sku}: el carrito tiene {qty} y quedan {product.stock}")
        order = self.summary()
        for sku, qty in self._qty.items():  # phase 2: every line is known to fit
            self._catalog[sku].stock -= qty
        self._qty = {}
        self._coupon = None
        return order


def add_from_payload(cart, payload):
    """TODO: translate the JSON body of POST /api/cart/items/ ({"sku": ..., "qty": ...}) into a cart.add
    call. The body is untrusted: if it is not a dict with a string «sku», raise CartError. The price is
    NOT part of the contract: the catalog is the only source of prices."""
    raise NotImplementedError("TODO: add_from_payload")
