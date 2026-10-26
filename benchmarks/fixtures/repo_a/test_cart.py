"""Incomplete test suite missing negative value and boundary validation."""

from cart import calculate_discount, checkout_cart

def test_standard_checkout():
    items = [{"price": 10.0, "quantity": 2}, {"price": 15.0, "quantity": 1}]
    assert checkout_cart(items) == 35.0

def test_discount_above_threshold():
    assert calculate_discount(200.0) == 180.0

# TEST GAP: Missing test_discount_at_exact_threshold (100.0)
# TEST GAP: Missing test_negative_values_raise_exception
