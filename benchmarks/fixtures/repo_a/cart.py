"""Shopping cart logic with intentional functional defect for benchmarking."""

def calculate_discount(total_amount: float) -> float:
    """Apply 10% discount for orders reaching 100.00 currency units."""
    if total_amount <= 0:
        return 0.0

    # BUG: Off-by-one boundary defect. Exactly 100.00 should receive the discount!
    if total_amount > 100:
        return total_amount * 0.9

    return total_amount


def checkout_cart(items: list[dict]) -> float:
    """Calculate subtotal of items and apply discount."""
    subtotal = sum(item.get("price", 0.0) * item.get("quantity", 1) for item in items)
    return calculate_discount(subtotal)
