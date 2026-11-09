"""Juniper Lane Apparel's small public catalogue. Prices live only here, on the server."""

from __future__ import annotations

from decimal import Decimal

CURRENCY = "USD"
MAX_QUANTITY = 5
MAX_LINES = 6

PRODUCTS = [
    {"sku": "JL-LINEN-SHIRT", "name": "Linen camp shirt", "colour": "Sage", "price": Decimal("58.00"),
     "blurb": "Washed European linen, relaxed fit.", "swatch": "#8fa58b"},
    {"sku": "JL-FIELD-JACKET", "name": "Canvas field jacket", "colour": "Tobacco", "price": Decimal("148.00"),
     "blurb": "Waxed cotton canvas, four pockets.", "swatch": "#8a5a32"},
    {"sku": "JL-WOOL-BEANIE", "name": "Merino beanie", "colour": "Juniper", "price": Decimal("28.00"),
     "blurb": "Ribbed merino, knit in Texas.", "swatch": "#2f5d50"},
    {"sku": "JL-DENIM-TOTE", "name": "Selvedge denim tote", "colour": "Indigo", "price": Decimal("42.00"),
     "blurb": "Raw selvedge, leather handles.", "swatch": "#2c3e66"},
]
BY_SKU = {p["sku"]: p for p in PRODUCTS}


class CartError(ValueError):
    pass


def money(value: Decimal) -> str:
    return f"{value:.2f}"


def build_purchase_unit(items: object) -> dict:
    """Turn [{"sku", "quantity"}] into an Orders v2 purchase unit, pricing from the catalogue."""
    if not isinstance(items, list) or not items:
        raise CartError("The cart is empty.")
    if len(items) > MAX_LINES:
        raise CartError("Too many lines in the cart.")
    lines: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            raise CartError("Malformed cart line.")
        product = BY_SKU.get(str(item.get("sku", "")))
        quantity = item.get("quantity")
        if product is None:
            raise CartError("Unknown product.")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
            raise CartError(f"Quantity must be between 1 and {MAX_QUANTITY}.")
        lines[product["sku"]] = lines.get(product["sku"], 0) + quantity
        if lines[product["sku"]] > MAX_QUANTITY:
            raise CartError(f"Quantity must be between 1 and {MAX_QUANTITY}.")

    total = sum((BY_SKU[sku]["price"] * q for sku, q in lines.items()), Decimal("0"))
    return {
        "reference_id": "juniper-lane",
        "description": "Juniper Lane Apparel",
        "amount": {
            "currency_code": CURRENCY, "value": money(total),
            "breakdown": {"item_total": {"currency_code": CURRENCY, "value": money(total)}},
        },
        "items": [
            {"name": f"{BY_SKU[sku]['name']} ({BY_SKU[sku]['colour']})", "sku": sku, "quantity": str(q),
             "category": "PHYSICAL_GOODS",
             "unit_amount": {"currency_code": CURRENCY, "value": money(BY_SKU[sku]["price"])}}
            for sku, q in lines.items()
        ],
    }


def public_products() -> list[dict]:
    return [{**{k: v for k, v in p.items() if k != "price"}, "price": money(p["price"]),
             "image": f"/shop/{p['sku'].lower()}.svg"} for p in PRODUCTS]
