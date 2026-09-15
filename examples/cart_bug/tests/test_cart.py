from cart import BULK_RATE, SHIPPING_FLAT, Item, cart_total


def test_empty_cart_is_shipping_only() -> None:
    """The reported bug. An empty cart still owes shipping."""
    assert cart_total([]) == SHIPPING_FLAT


def test_single_item_has_no_bulk_discount() -> None:
    assert cart_total([Item(price=10.0, qty=1)]) == round(10.0 + SHIPPING_FLAT, 2)


def test_bulk_discount_applies_to_the_cheapest_item() -> None:
    items = [Item(price=10.0, qty=2), Item(price=4.0, qty=1)]
    expected = round(24.0 + SHIPPING_FLAT - 4.0 * BULK_RATE, 2)
    assert cart_total(items) == expected


def test_shipping_is_always_added() -> None:
    assert cart_total([Item(price=1.0, qty=1)]) > 1.0
