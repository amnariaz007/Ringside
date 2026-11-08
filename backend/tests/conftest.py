import pytest


@pytest.fixture
def seller(django_user_model):
    return django_user_model.objects.create_user("seller@shop.example", password="correct-horse-battery")


@pytest.fixture
def client(client, seller):
    """API tests run as a logged-in seller; tests/test_auth.py checks the anonymous side."""
    client.force_login(seller)
    return client
