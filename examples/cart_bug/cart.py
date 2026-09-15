"""A tiny cart total, deliberately incomplete.

The bulk discount is computed before anything checks that the cart has
contents. This is the Debug Agent demo fixture: small enough that a real
provider run costs almost nothing, broken in exactly one place, and wrong in a
way whose obvious fix is in the wrong function.
"""

from dataclasses import dataclass

SHIPPING_FLAT = 4.99
BULK_UNITS = 3
BULK_RATE = 0.10


@dataclass(frozen=True)
class Item:
    price: float
    qty: int


def _discount(items: list[Item]) -> float:
    """Take BULK_RATE off the cheapest item once the cart holds BULK_UNITS."""
    cheapest = min(item.price for item in items)
    if sum(item.qty for item in items) < BULK_UNITS:
        return 0.0
    return cheapest * BULK_RATE


def cart_total(items: list[Item]) -> float:
    """Subtotal plus flat shipping, less any bulk discount."""
    subtotal = sum(item.price * item.qty for item in items)
    return round(subtotal + SHIPPING_FLAT - _discount(items), 2)
