"""Login, logout, CSRF and the anonymous lock-out."""

import json

import pytest
from django.core.cache import cache
from django.test import Client

pytestmark = pytest.mark.django_db
PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def clear_rate_limit():
    cache.clear()


@pytest.fixture
def anon():
    return Client(enforce_csrf_checks=True)


def csrf(c):
    c.get("/api/auth/me/")
    return c.cookies["csrftoken"].value


def login(c, username, password, token=None):
    return c.post("/api/auth/login/", data=json.dumps({"username": username, "password": password}),
                  content_type="application/json", HTTP_X_CSRFTOKEN=token or csrf(c))


@pytest.mark.parametrize("path", ["/api/orders/", "/api/dashboard/", "/api/graph/rings/", "/api/audit/",
                                  "/api/disputes/", "/api/disputes/1/copilot/"])
def test_api_requires_login(anon, path):
    assert anon.get(path).status_code == 403


def test_health_and_webhook_stay_public(anon):
    assert anon.get("/api/health/").status_code == 200
    # Webhook rejects forged events on signature, not on login.
    resp = anon.post("/api/webhooks/paypal/", data="{}", content_type="application/json")
    assert resp.status_code == 400


def test_login_flow(anon, seller):
    assert anon.get("/api/auth/me/").json() == {"authenticated": False}
    resp = login(anon, seller.username, PASSWORD)
    assert resp.status_code == 200 and resp.json()["user"]["username"] == seller.username
    assert anon.get("/api/orders/").status_code == 200
    assert anon.get("/api/auth/me/").json()["authenticated"] is True
    out = anon.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=anon.cookies["csrftoken"].value)
    assert out.status_code == 200 and anon.get("/api/orders/").status_code == 403


def test_wrong_password(anon, seller):
    resp = login(anon, seller.username, "nope")
    assert resp.status_code == 400 and "don't match" in resp.json()["detail"]


def test_login_needs_csrf_token(anon, seller):
    anon.get("/api/auth/me/")
    resp = anon.post("/api/auth/login/", data=json.dumps({"username": seller.username, "password": PASSWORD}),
                     content_type="application/json")
    assert resp.status_code == 403


def test_logged_in_posts_need_csrf(anon, seller):
    login(anon, seller.username, PASSWORD)
    resp = anon.post("/api/disputes/1/copilot/regenerate/")  # no CSRF header
    assert resp.status_code == 403


def test_rate_limit_after_ten_failures(anon, seller):
    token = csrf(anon)
    for _ in range(10):
        assert login(anon, seller.username, "wrong", token).status_code == 400
    assert login(anon, seller.username, PASSWORD, token).status_code == 429


def test_demo_user_command_requires_strong_password(monkeypatch):
    from django.core.management import call_command
    from django.core.management.base import CommandError
    monkeypatch.setenv("DEMO_USERNAME", "judge@example.com")
    monkeypatch.setenv("DEMO_PASSWORD", "short")
    with pytest.raises(CommandError):
        call_command("ensure_demo_user")
    monkeypatch.setenv("DEMO_PASSWORD", "a-long-enough-password")
    call_command("ensure_demo_user")
    from django.contrib.auth import get_user_model
    assert get_user_model().objects.get(username="judge@example.com").check_password("a-long-enough-password")
