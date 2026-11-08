"""
Builders for PayPal-shaped JSON, following the REST API reference.

Used by the mock client, the demo seed and the tests. Keeping one source of
truth for payload shapes means the parser in ingest.py is tested against the
same structures the sandbox returns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal


def _id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:17].upper()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def order(
    *,
    merchant_id: str,
    payer_id: str,
    email: str,
    given_name: str,
    surname: str,
    payer_country: str,
    amount: Decimal | str,
    created_at: datetime,
    ship_line1: str,
    ship_city: str,
    ship_postal: str,
    ship_country: str,
    ship_line2: str = "",
    ship_state: str = "",
    phone: str = "",
    account_status: str = "VERIFIED",
    seller_protection: str = "ELIGIBLE",
    currency: str = "USD",
    order_id: str | None = None,
    capture_id: str | None = None,
) -> dict:
    """A COMPLETED Orders v2 order with one capture (GET /v2/checkout/orders/{id})."""
    order_id = order_id or _id()
    capture_id = capture_id or _id("CAP")
    value = f"{Decimal(str(amount)):.2f}"
    captured_at = created_at + timedelta(seconds=40)
    payer = {
        "name": {"given_name": given_name, "surname": surname},
        "email_address": email,
        "payer_id": payer_id,
        "address": {"country_code": payer_country},
    }
    if phone:
        payer["phone"] = {"phone_number": {"national_number": phone}}
    protection = {"status": seller_protection}
    if seller_protection != "NOT_ELIGIBLE":
        protection["dispute_categories"] = ["ITEM_NOT_RECEIVED", "UNAUTHORIZED_TRANSACTION"]
    return {
        "id": order_id,
        "intent": "CAPTURE",
        "status": "COMPLETED",
        "create_time": _ts(created_at),
        "update_time": _ts(captured_at),
        "payment_source": {
            "paypal": {
                "account_id": payer_id,
                "account_status": account_status,
                "email_address": email,
                "name": {"given_name": given_name, "surname": surname},
                "address": {"country_code": payer_country},
            }
        },
        "payer": payer,
        "purchase_units": [
            {
                "reference_id": "default",
                "amount": {"currency_code": currency, "value": value},
                "payee": {"merchant_id": merchant_id},
                "shipping": {
                    "name": {"full_name": f"{given_name} {surname}"},
                    "address": {
                        "address_line_1": ship_line1,
                        "address_line_2": ship_line2,
                        "admin_area_2": ship_city,
                        "admin_area_1": ship_state,
                        "postal_code": ship_postal,
                        "country_code": ship_country,
                    },
                },
                "payments": {
                    "captures": [
                        {
                            "id": capture_id,
                            "status": "COMPLETED",
                            "amount": {"currency_code": currency, "value": value},
                            "final_capture": True,
                            "seller_protection": protection,
                            "create_time": _ts(captured_at),
                            "update_time": _ts(captured_at),
                        }
                    ]
                },
            }
        ],
    }


def refund(*, capture_id: str, amount: Decimal | str, created_at: datetime, currency: str = "USD") -> dict:
    """A Payments v2 refund (resource of PAYMENT.CAPTURE.REFUNDED)."""
    return {
        "id": _id("RF"),
        "status": "COMPLETED",
        "amount": {"currency_code": currency, "value": f"{Decimal(str(amount)):.2f}"},
        "create_time": _ts(created_at),
        "update_time": _ts(created_at),
        "links": [
            {"rel": "up", "method": "GET",
             "href": f"https://api-m.sandbox.paypal.com/v2/payments/captures/{capture_id}"},
        ],
    }


def dispute(
    *,
    capture_id: str,
    amount: Decimal | str,
    created_at: datetime,
    reason: str = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    status: str = "WAITING_FOR_SELLER_RESPONSE",
    outcome: str = "",
    currency: str = "USD",
    buyer_message: str = "",
    dispute_id: str | None = None,
    updated_at: datetime | None = None,
) -> dict:
    """A Disputes v1 dispute (GET /v1/customer/disputes/{id})."""
    updated_at = updated_at or created_at
    data = {
        "dispute_id": dispute_id or _id("PP-D-"),
        "create_time": _ts(created_at),
        "update_time": _ts(updated_at),
        "disputed_transactions": [{"seller_transaction_id": capture_id}],
        "reason": reason,
        "status": status,
        "dispute_state": "REQUIRED_ACTION" if status == "WAITING_FOR_SELLER_RESPONSE" else "",
        "dispute_amount": {"currency_code": currency, "value": f"{Decimal(str(amount)):.2f}"},
        "dispute_life_cycle_stage": "INQUIRY",
        "dispute_channel": "INTERNAL",
        "messages": [],
    }
    if status == "WAITING_FOR_SELLER_RESPONSE":
        data["seller_response_due_date"] = _ts(created_at + timedelta(days=10))
    if outcome:
        data["dispute_outcome"] = {"outcome_code": outcome}
    if buyer_message:
        # Untrusted text from the buyer. Stored, displayed, never obeyed.
        data["messages"].append({"posted_by": "BUYER", "time_posted": _ts(created_at), "content": buyer_message})
    return data


def webhook_event(event_type: str, resource: dict, *, resource_type: str, created_at: datetime) -> dict:
    """A Webhooks v1 event envelope."""
    return {
        "id": _id("WH-"),
        "event_version": "1.0",
        "create_time": _ts(created_at),
        "resource_type": resource_type,
        "event_type": event_type,
        "summary": event_type.replace(".", " ").lower(),
        "resource": resource,
    }


def capture_completed_event(order_json: dict, created_at: datetime) -> dict:
    capture = dict(order_json["purchase_units"][0]["payments"]["captures"][0])
    capture["supplementary_data"] = {"related_ids": {"order_id": order_json["id"]}}
    return webhook_event("PAYMENT.CAPTURE.COMPLETED", capture, resource_type="capture", created_at=created_at)
