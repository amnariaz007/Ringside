"""
Turn PayPal JSON into PayGuard rows. Every function is idempotent: feeding
the same payload twice updates rather than duplicates.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils.dateparse import parse_datetime

from core import normalize
from core.models import Address, Buyer, Capture, Dispute, Order, Refund, Seller
from risk.lists import RESHIPPER_KEYWORDS


REDACTED = "[redacted]"


def redact(data: dict) -> dict:
    """
    Copy of a PayPal payload with buyer contact details removed. Emails and
    phones are kept only as salted hashes on Buyer; the raw JSON we store for
    debugging must not quietly undo that.
    """
    def walk(node, key=""):
        if isinstance(node, dict):
            return {k: (REDACTED if k in {"email_address", "email", "phone_number", "national_number"}
                        else walk(v, k)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        return node
    out = walk(data)
    payer = out.get("payer")
    if isinstance(payer, dict) and "phone" in payer:
        payer["phone"] = REDACTED
    return out


class MissingDependency(Exception):
    """The payload refers to something we haven't seen yet (out-of-order webhook)."""


def _dt(value: str):
    dt = parse_datetime(value)
    if dt is None:
        raise ValueError(f"bad PayPal timestamp: {value!r}")
    return dt


def _money(obj: dict) -> tuple[Decimal, str]:
    return Decimal(obj["value"]), obj["currency_code"]


def _upsert_address(addr: dict | None) -> Address | None:
    if not addr or not addr.get("address_line_1"):
        return None
    line1, line2 = addr.get("address_line_1", ""), addr.get("address_line_2", "")
    city, postal = addr.get("admin_area_2", ""), addr.get("postal_code", "")
    country = addr.get("country_code", "")
    key = normalize.address_key(line1, line2, city, postal, country)
    text = normalize.normalize_address_text(f"{line1} {line2}")
    address, _ = Address.objects.get_or_create(
        normalized_key=key,
        defaults={
            "line1": line1, "line2": line2, "city": city, "state": addr.get("admin_area_1", ""),
            "postal_code": postal, "country_code": country,
            "is_reshipper": any(k in text for k in RESHIPPER_KEYWORDS),
        },
    )
    return address


def _upsert_buyer(order_json: dict, seen_at) -> Buyer:
    payer = order_json["payer"]
    source = order_json.get("payment_source", {}).get("paypal", {})
    email = payer.get("email_address") or source.get("email_address", "")
    name = payer.get("name", {})
    phone = payer.get("phone", {}).get("phone_number", {}).get("national_number", "")
    defaults = {
        "email_hash": normalize.hash_email(email),
        "email_stem_hash": normalize.hash_email_stem(email),
        "email_domain": normalize.email_domain(email),
        "phone_hash": normalize.hash_phone(phone),
        "display_name": f"{name.get('given_name', '')} {name.get('surname', '')}".strip(),
        "country_code": payer.get("address", {}).get("country_code", ""),
        "account_status": source.get("account_status", ""),
    }
    buyer, created = Buyer.objects.get_or_create(
        payer_id=payer["payer_id"], defaults={**defaults, "first_seen_at": seen_at}
    )
    if not created:
        for k, v in defaults.items():
            if v:
                setattr(buyer, k, v)
        if seen_at < buyer.first_seen_at:
            buyer.first_seen_at = seen_at
        buyer.save()
    return buyer


@transaction.atomic
def ingest_order(order_json: dict) -> tuple[Order, bool]:
    """Store an Orders v2 order and its captures. Returns (order, created)."""
    unit = order_json["purchase_units"][0]
    merchant_id = unit.get("payee", {}).get("merchant_id", "")
    try:
        seller = Seller.objects.get(paypal_merchant_id=merchant_id)
    except Seller.DoesNotExist as exc:
        raise MissingDependency(f"unknown seller merchant_id={merchant_id!r}") from exc

    created_at = _dt(order_json["create_time"])
    amount, currency = _money(unit["amount"])
    order, created = Order.objects.update_or_create(
        paypal_order_id=order_json["id"],
        defaults={
            "seller": seller,
            "buyer": _upsert_buyer(order_json, created_at),
            "shipping_address": _upsert_address(unit.get("shipping", {}).get("address")),
            "amount": amount,
            "currency": currency,
            "payer_country": order_json["payer"].get("address", {}).get("country_code", ""),
            "status": order_json["status"],
            "created_at": created_at,
            "raw": redact(order_json),
        },
    )
    for cap in unit.get("payments", {}).get("captures", []):
        cap_amount, _ = _money(cap["amount"])
        protection = cap.get("seller_protection", {})
        Capture.objects.update_or_create(
            paypal_capture_id=cap["id"],
            defaults={
                "order": order,
                "amount": cap_amount,
                "status": cap["status"],
                "seller_protection_status": protection.get("status", ""),
                "seller_protection_categories": protection.get("dispute_categories", []),
                "captured_at": _dt(cap["create_time"]),
            },
        )
    return order, created


def _capture_id_from_refund(refund_json: dict) -> str:
    for link in refund_json.get("links", []):
        if link.get("rel") == "up" and "/captures/" in link.get("href", ""):
            return link["href"].rstrip("/").rsplit("/", 1)[-1]
    raise ValueError("refund payload has no 'up' link to its capture")


@transaction.atomic
def ingest_refund(refund_json: dict) -> Refund:
    capture_id = _capture_id_from_refund(refund_json)
    try:
        capture = Capture.objects.get(paypal_capture_id=capture_id)
    except Capture.DoesNotExist as exc:
        raise MissingDependency(f"refund for unknown capture {capture_id}") from exc
    amount, _ = _money(refund_json["amount"])
    refund, _ = Refund.objects.update_or_create(
        paypal_refund_id=refund_json["id"],
        defaults={
            "capture": capture, "amount": amount, "status": refund_json["status"],
            "created_at": _dt(refund_json["create_time"]),
        },
    )
    return refund


@transaction.atomic
def ingest_dispute(dispute_json: dict) -> tuple[Dispute, bool]:
    """Upsert a dispute. Ignores payloads older than what we already have (out-of-order updates)."""
    updated_at = _dt(dispute_json["update_time"])
    existing = Dispute.objects.filter(paypal_dispute_id=dispute_json["dispute_id"]).first()
    if existing and existing.updated_at >= updated_at:
        return existing, False

    capture = None
    txns = dispute_json.get("disputed_transactions") or []
    if txns and txns[0].get("seller_transaction_id"):
        capture = Capture.objects.filter(paypal_capture_id=txns[0]["seller_transaction_id"]).select_related("order").first()
        if capture is None:
            raise MissingDependency(f"dispute for unknown capture {txns[0]['seller_transaction_id']}")

    amount, currency = _money(dispute_json["dispute_amount"])
    due = dispute_json.get("seller_response_due_date")
    dispute, created = Dispute.objects.update_or_create(
        paypal_dispute_id=dispute_json["dispute_id"],
        defaults={
            "capture": capture,
            "order": capture.order if capture else None,
            "reason": dispute_json["reason"],
            "status": dispute_json["status"],
            "dispute_state": dispute_json.get("dispute_state", ""),
            "amount": amount,
            "currency": currency,
            "seller_response_due_at": _dt(due) if due else None,
            "outcome": dispute_json.get("dispute_outcome", {}).get("outcome_code", ""),
            "created_at": _dt(dispute_json["create_time"]),
            "updated_at": updated_at,
            "raw": redact(dispute_json),
        },
    )
    return dispute, created
