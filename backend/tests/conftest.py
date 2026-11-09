import pytest


@pytest.fixture(autouse=True)
def offline_ai(settings):
    """Tests never call real AI or PayPal, whatever a developer's .env says."""
    settings.AI_PROVIDER = "template"
    settings.GEMINI_API_KEY = ""
    settings.PAYPAL_MODE = "mock"
    settings.PAYPAL_CLIENT_ID = settings.PAYPAL_CLIENT_SECRET = ""
    settings.PAYPAL_WEBHOOK_ID = settings.PAYPAL_MERCHANT_ID = ""
    settings.PAYPAL_API_BASE = "https://api-m.sandbox.paypal.com"

@pytest.fixture
def seller(django_user_model):
    return django_user_model.objects.create_user("seller@shop.example", password="correct-horse-battery")


@pytest.fixture
def client(client, seller):
    """API tests run as a logged-in seller; tests/test_auth.py checks the anonymous side."""
    client.force_login(seller)
    return client
