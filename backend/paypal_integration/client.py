"""
One PayPal client interface, two implementations.

    PAYPAL_MODE=mock     MockPayPalClient: reads PayPal-shaped JSON from the DB
    PAYPAL_MODE=sandbox  SandboxPayPalClient: real HTTP calls to the sandbox

The rest of the app only ever calls get_client(), so switching to the real
sandbox is a settings change, not a rewrite. Payload shapes follow the PayPal
REST docs (Orders v2, Payments v2, Disputes v1, Webhooks v1).
"""

from __future__ import annotations

import time
from typing import Protocol

import requests
from django.conf import settings

from .models import MockPayPalObject

WEBHOOK_HEADERS = (
    "PAYPAL-AUTH-ALGO",
    "PAYPAL-CERT-URL",
    "PAYPAL-TRANSMISSION-ID",
    "PAYPAL-TRANSMISSION-SIG",
    "PAYPAL-TRANSMISSION-TIME",
)

MOCK_VALID_SIGNATURE = "mock-valid-signature"


class PayPalError(Exception):
    pass


class PayPalNotFound(PayPalError):
    pass


class PayPalClient(Protocol):
    mode: str

    def get_order(self, order_id: str) -> dict: ...
    def get_dispute(self, dispute_id: str) -> dict: ...
    def verify_webhook_signature(self, headers: dict[str, str], raw_body: bytes) -> bool: ...


class MockPayPalClient:
    mode = "mock"

    def _get(self, kind: str, paypal_id: str) -> dict:
        try:
            return MockPayPalObject.objects.get(kind=kind, paypal_id=paypal_id).data
        except MockPayPalObject.DoesNotExist as exc:
            raise PayPalNotFound(f"mock {kind} {paypal_id} not found") from exc

    def get_order(self, order_id: str) -> dict:
        return self._get("order", order_id)

    def get_dispute(self, dispute_id: str) -> dict:
        return self._get("dispute", dispute_id)

    def verify_webhook_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        # Lets tests and the simulator exercise the "forged event" path.
        return headers.get("PAYPAL-TRANSMISSION-SIG") == MOCK_VALID_SIGNATURE

    # Helpers used by the simulator and tests (not part of the real interface).
    @staticmethod
    def put(kind: str, paypal_id: str, data: dict) -> None:
        MockPayPalObject.objects.update_or_create(kind=kind, paypal_id=paypal_id, defaults={"data": data})


class SandboxPayPalClient:
    """
    Real sandbox client. Written against the docs; NOT yet run against PayPal
    because the developer account is pending. See docs/VERIFICATION.md.
    """

    mode = "sandbox"
    _token: str = ""
    _token_expires_at: float = 0.0

    def __init__(self):
        if not (settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET):
            raise PayPalError("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET must be set for sandbox mode")
        self.base = settings.PAYPAL_API_BASE.rstrip("/")

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = requests.post(
            f"{self.base}/v1/oauth2/token",
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=15,
        )
        if resp.status_code != 200:
            raise PayPalError(f"OAuth failed: {resp.status_code} {resp.text[:200]}")
        body = resp.json()
        SandboxPayPalClient._token = body["access_token"]
        SandboxPayPalClient._token_expires_at = time.time() + int(body.get("expires_in", 0))
        return self._token

    def _request(self, method: str, path: str, **kwargs) -> dict:
        headers = {"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        resp = requests.request(method, f"{self.base}{path}", headers=headers, timeout=20, **kwargs)
        if resp.status_code == 404:
            raise PayPalNotFound(f"{method} {path} -> 404")
        if resp.status_code >= 400:
            debug_id = resp.headers.get("PayPal-Debug-Id", "")
            raise PayPalError(f"{method} {path} -> {resp.status_code} (debug {debug_id}): {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def get_order(self, order_id: str) -> dict:
        return self._request("GET", f"/v2/checkout/orders/{order_id}")

    def get_dispute(self, dispute_id: str) -> dict:
        return self._request("GET", f"/v1/customer/disputes/{dispute_id}")

    def verify_webhook_signature(self, headers: dict[str, str], raw_body: bytes) -> bool:
        if not settings.PAYPAL_WEBHOOK_ID:
            raise PayPalError("PAYPAL_WEBHOOK_ID must be set to verify webhooks")
        if any(not headers.get(h) for h in WEBHOOK_HEADERS):
            return False
        # Splice the raw body in byte-for-byte: re-serialising the JSON can
        # reorder keys or change number formats and break verification.
        import json
        prefix = json.dumps({
            "auth_algo": headers["PAYPAL-AUTH-ALGO"],
            "cert_url": headers["PAYPAL-CERT-URL"],
            "transmission_id": headers["PAYPAL-TRANSMISSION-ID"],
            "transmission_sig": headers["PAYPAL-TRANSMISSION-SIG"],
            "transmission_time": headers["PAYPAL-TRANSMISSION-TIME"],
            "webhook_id": settings.PAYPAL_WEBHOOK_ID,
        })[:-1]
        body = f'{prefix}, "webhook_event": {raw_body.decode()}}}'
        result = self._request("POST", "/v1/notifications/verify-webhook-signature", data=body)
        return result.get("verification_status") == "SUCCESS"


def get_client() -> PayPalClient:
    if settings.PAYPAL_MODE == "sandbox":
        return SandboxPayPalClient()
    return MockPayPalClient()
