"""
The sandbox client hasn't been run against PayPal yet (no developer account),
so these tests pin down the requests it will send.
"""

import json
from unittest import mock

import pytest

from paypal_integration.client import PayPalError, SandboxPayPalClient

HEADERS = {
    "PAYPAL-AUTH-ALGO": "SHA256withRSA",
    "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert.pem",
    "PAYPAL-TRANSMISSION-ID": "tx-1",
    "PAYPAL-TRANSMISSION-SIG": "sig",
    "PAYPAL-TRANSMISSION-TIME": "2026-11-08T12:00:00Z",
}


@pytest.fixture
def sandbox(settings):
    settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET = "id", "secret"
    settings.PAYPAL_WEBHOOK_ID = "WH-123"
    SandboxPayPalClient._token, SandboxPayPalClient._token_expires_at = "", 0.0
    return SandboxPayPalClient()


def ok(payload, status=200):
    r = mock.Mock(status_code=status, content=b"x", headers={})
    r.json.return_value = payload
    return r


def test_requires_credentials(settings):
    settings.PAYPAL_CLIENT_ID = ""
    with pytest.raises(PayPalError):
        SandboxPayPalClient()


def test_verify_splices_raw_body_unchanged(sandbox):
    # Key order and number formatting that json.dumps would change:
    raw = b'{"id":"WH-1","event_type":"X","resource":{"amount":10.50}}'
    with mock.patch("requests.post", return_value=ok({"access_token": "T", "expires_in": 3600})), \
         mock.patch("requests.request", return_value=ok({"verification_status": "SUCCESS"})) as req:
        assert sandbox.verify_webhook_signature(HEADERS, raw) is True
    sent = req.call_args.kwargs["data"]
    assert raw.decode() in sent
    body = json.loads(sent)
    assert body["webhook_id"] == "WH-123" and body["transmission_id"] == "tx-1"
    assert req.call_args.args[1].endswith("/v1/notifications/verify-webhook-signature")


def test_verify_fails_closed_when_headers_missing(sandbox):
    with mock.patch("requests.request") as req:
        assert sandbox.verify_webhook_signature({}, b"{}") is False
    req.assert_not_called()


def test_verify_returns_false_on_failure_status(sandbox):
    with mock.patch("requests.post", return_value=ok({"access_token": "T", "expires_in": 3600})), \
         mock.patch("requests.request", return_value=ok({"verification_status": "FAILURE"})):
        assert sandbox.verify_webhook_signature(HEADERS, b'{"id":"1"}') is False


def test_access_token_is_cached(sandbox):
    with mock.patch("requests.post", return_value=ok({"access_token": "T", "expires_in": 3600})) as post, \
         mock.patch("requests.request", return_value=ok({"id": "ORD"})):
        sandbox.get_order("ORD")
        sandbox.get_order("ORD")
    assert post.call_count == 1
